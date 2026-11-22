"""A planned workflow with durable checkpoints and per-draft invalidation."""

import json

from . import decision as decision_contract
from .contracts import HarnessError, digest, encode, validate
from .evidence import audit_evidence
from .registry import skill_registry
from .research import dependencies_changed, review, source_dependencies
from .planning import DEFAULT, HANDOFF_KINDS, OUTPUTS, PARENTS, plan
from .store import Store

STRATEGY_FIELDS = ("product", "audience", "goal")
OPTIONAL_FIELDS = {"market", "budget"}
PRODUCT_ONLY = {"pricing", "capabilities"}
DRAFT_FIELDS = {
    "positioning": STRATEGY_FIELDS,
    "pricing": ("price",),
    "capabilities": ("capabilities",),
    "launch-plan": ("product", "audience", "goal", "capabilities"),
    "sales-plan": ("product", "audience", "goal", "price", "capabilities"),
    "experiment-plan": ("product", "audience", "goal", "price", "capabilities"),
}


class Harness(Store):
    def _project(self):
        row = self.db.execute("SELECT * FROM project").fetchone()
        if row is None:
            raise HarnessError("initialize a project first")
        return row

    def _inputs(self):
        rows = self.db.execute("""
            SELECT e.* FROM evidence e
            WHERE revision = (SELECT max(revision) FROM evidence WHERE field = e.field)
        """)
        return {
            row["field"]: (json.loads(row["value"]), json.loads(row["data"]))
            for row in rows
            if row["value"] != "null"
        }

    def _save_evidence(self, field, revision, value):
        evidence = validate(
            "evidence",
            {
                "field": field,
                "revision": revision,
                "source": "operator_input",
                "sha256": digest(value),
            },
        )
        self.db.execute(
            "INSERT INTO evidence VALUES (?, ?, ?, ?)",
            (field, revision, encode(value), encode(evidence)),
        )

    def initialize(self, data):
        validate("project-input", data)
        review(data["values"].get("market_sources", []))
        with self.transaction():
            if self.db.execute("SELECT 1 FROM project").fetchone():
                raise HarnessError("database already has a project")
            self.db.execute("INSERT INTO project VALUES (?, 1)", (data["project_id"],))
            for field, value in data["values"].items():
                self._save_evidence(field, 1, value)

    def update(self, patch):
        validate("context-patch", patch)
        if "market_sources" in patch:
            review(patch["market_sources"])
        with self.transaction():
            return self._apply_patch(patch)

    def restore(self, revision):
        if type(revision) is not int or revision < 1:
            raise HarnessError("revision must be a positive integer")
        with self.transaction():
            if revision > self._project()["revision"]:
                raise HarnessError("unknown context revision")
            old = {
                row["field"]: json.loads(row["value"])
                for row in self.db.execute(
                    """
                SELECT e.* FROM evidence e WHERE revision = (
                    SELECT max(revision) FROM evidence WHERE field = e.field AND revision <= ?
                )""",
                    (revision,),
                )
            }
            current = self._inputs()
            return self._apply_patch({**dict.fromkeys(current), **old})

    def _apply_patch(self, patch):
        project, inputs = self._project(), self._inputs()
        changes = {
            field: value
            for field, value in patch.items()
            if field not in inputs or encode(value) != encode(inputs[field][0])
        }
        revision = project["revision"]
        if not changes:
            return {"revision": revision, "stale_artifact_ids": []}
        revision += 1
        self.db.execute("UPDATE project SET revision = ?", (revision,))
        for field, value in changes.items():
            self._save_evidence(field, revision, value)
        stale = self._invalidate(set(changes) - {"market_sources"})
        if "market_sources" in changes:
            for run in self.db.execute("SELECT id FROM runs").fetchall():
                stale.extend(self._refresh_market(run["id"], inputs_changed=True))
        return {"revision": revision, "stale_artifact_ids": sorted(stale)}

    def _invalidate(self, fields_changed, only_run=None):
        stale = []
        for row in self.db.execute(
            "SELECT id, data FROM artifacts WHERE stale=0 AND (? IS NULL OR run_id=?)",
            (only_run, only_run),
        ).fetchall():
            deps = json.loads(row["data"])["dependencies"]
            market_aware = json.loads(row["data"]).get("market_status") is not None
            if any(ref["field"] in fields_changed for ref in deps) or (
                market_aware and fields_changed & OPTIONAL_FIELDS
            ):
                stale.append(row["id"])
                self.db.execute("UPDATE artifacts SET stale = 1 WHERE id = ?", (row["id"],))
        for run in self.db.execute(
            "SELECT id FROM runs WHERE ? IS NULL OR id = ?", (only_run, only_run)
        ).fetchall():
            run_id = run["id"]
            for task in self._tasks(run_id):
                stage = task["stage"]
                fields = (
                    {*STRATEGY_FIELDS, "market_sources"}
                    if stage == "strategy"
                    else {f for kind in self._kinds(stage) for f in DRAFT_FIELDS[kind]}
                )
                if not (fields | OPTIONAL_FIELDS) & fields_changed:
                    continue
                if stage == "strategy":
                    self.db.execute("UPDATE runs SET decision_id = NULL WHERE id = ?", (run_id,))
                if task["status"] == "succeeded" and stage != "strategy":
                    current = self._active(run_id)
                    if all(kind in current for kind in self._kinds(stage)):
                        continue
                status = (
                    "pending"
                    if stage == "content"
                    and "strategy" in self._plan(run_id)
                    and self._run(run_id)["decision_id"] is None
                    else "queued"
                )
                self._set_task(run_id, stage, status)
        return stale

    def _market(self):
        return review(self._inputs().get("market_sources", ([], None))[0])

    def _refresh_market(self, run_id, *, inputs_changed=False):
        market = self._market()
        decision_id = self._run(run_id)["decision_id"]

        def invalid(data):
            if "market_status" not in data:
                return False
            snapshots = data.get("source_dependencies")
            if snapshots is not None:
                if data.get("claims") or data.get("citation_ids"):
                    return dependencies_changed(market, snapshots)
                return snapshots != source_dependencies(market, [])
            return inputs_changed or (
                market["status"],
                market["citation_ids"],
                market["contradictions"],
            ) != (
                data["market_status"],
                data.get("eligible_citation_ids", []),
                data.get("contradictions", []),
            )

        decision_stale = False
        if decision_id is not None:
            saved = self.db.execute(
                "SELECT data FROM decisions WHERE id=?", (decision_id,)
            ).fetchone()
            decision_stale = invalid(json.loads(saved["data"]))
            if decision_stale:
                self.db.execute("UPDATE runs SET decision_id=NULL WHERE id=?", (run_id,))
                self._set_task(run_id, "strategy", "queued")
        stale = set()
        # Handoffs point to previously inserted artifacts, so ordered traversal propagates once.
        rows = self.db.execute(
            "SELECT id, data FROM artifacts WHERE stale=0 AND run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        for row in rows:
            data = json.loads(row["data"])
            if (
                (decision_stale and data.get("decision_id") == decision_id)
                or stale.intersection(data.get("handoff_ids", ()))
                or invalid(data)
            ):
                stale.add(row["id"])
                self.db.execute("UPDATE artifacts SET stale=1 WHERE id=?", (row["id"],))
        current = self._active(run_id)
        for task in self._tasks(run_id):
            stage = task["stage"]
            if inputs_changed and task["status"] == "running":
                self._set_task(run_id, stage, "queued")
            if (
                stage != "strategy"
                and task["status"] == "succeeded"
                and any(kind not in current for kind in self._kinds(stage))
            ):
                self._set_task(run_id, stage, "queued")
        return stale

    def revise_decision(self, run_id, patch, *, reason, expected_revision=None):
        """Append an operator-approved revision and retire drafts bound to the old one."""
        with self.transaction():
            actor = self.operator_identity()
            validate("decision-patch", patch)
            run = self._run(run_id)
            if run["decision_id"] is None:
                raise HarnessError("run has no active decision to revise")
            row = self.db.execute(
                "SELECT id, data FROM decisions WHERE id = ?", (run["decision_id"],)
            ).fetchone()
            saved = json.loads(row["data"])
            contract = self._contract(row["id"], saved)
            if expected_revision is not None and expected_revision != contract["decision_revision"]:
                raise HarnessError("decision revision changed; inspect the active contract before approving")
            updated = decision_contract.revise(contract, patch, reason=reason, actor=actor)
            receipt = {
                "principal": actor, "contract_sha256": digest(updated),
                "prior_sha256": digest(contract), "patch_sha256": digest(patch),
            }
            ident = self.db.execute(
                "INSERT INTO decisions(run_id,data) VALUES (?,?)",
                (run_id, encode(validate("decision", {
                    **saved, "contract": updated, "operator_approval": receipt,
                }))),
            ).lastrowid
            self.db.execute("UPDATE runs SET decision_id = ? WHERE id = ?", (ident, run_id))
            stale = []
            for artifact in self.db.execute(
                "SELECT id, data FROM artifacts WHERE run_id = ? AND stale = 0", (run_id,)
            ).fetchall():
                if json.loads(artifact["data"]).get("decision_id") == row["id"]:
                    self.db.execute(
                        "UPDATE artifacts SET stale = 1 WHERE id = ?", (artifact["id"],)
                    )
                    stale.append(artifact["id"])
            current = self._active(run_id)
            for task in self._tasks(run_id):
                stage = task["stage"]
                if stage == "strategy":
                    continue
                if task["status"] == "running" or (
                    task["status"] == "succeeded"
                    and any(kind not in current for kind in self._kinds(stage))
                ):
                    self._set_task(run_id, stage, "queued")
            self._event(
                run_id,
                "strategy",
                0,
                {
                    "status": "decision_revised",
                    "decision_id": updated["decision_id"],
                    "decision_revision": updated["decision_revision"],
                    "reason": reason,
                    "operator_approval": receipt,
                },
            )
            return {
                "decision_id": updated["decision_id"],
                "decision_revision": updated["decision_revision"],
                "stale_artifact_ids": sorted(stale),
            }

    def start(self, run_id, execution="fixture", *, stages=None, goal=None):
        validate("run-id", run_id)
        if execution not in {"fixture", "model", "handoff"}:
            raise HarnessError("unsupported execution mode")
        stages = plan(stages, goal)
        registry = skill_registry()
        pins = encode({stage: registry[stage] for stage in stages})
        with self.transaction():
            self._project()
            existing = self.db.execute(
                "SELECT execution, plan FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
            if existing:
                if existing["execution"] != execution:
                    raise HarnessError("run already uses another execution mode")
                if (json.loads(existing["plan"]) if existing["plan"] else list(DEFAULT)) != stages:
                    raise HarnessError("run already has a different plan")
                return
            self.db.execute(
                "INSERT INTO runs(id,registry,execution,plan) VALUES (?, ?, ?, ?)",
                (run_id, pins, execution, encode(stages)),
            )
            self.db.executemany(
                "INSERT INTO tasks VALUES (?, ?, ?, 0, NULL)",
                [
                    (
                        run_id,
                        stage,
                        "pending" if set(PARENTS[stage]) & set(stages) else "queued",
                    )
                    for stage in stages
                ],
            )

    def _run(self, run_id):
        run = self.db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            raise HarnessError("unknown run")
        return run

    def _plan(self, run_id):
        saved = self._run(run_id)["plan"]
        return json.loads(saved) if saved else list(DEFAULT)

    def _tasks(self, run_id):
        rows = {
            r["stage"]: r
            for r in self.db.execute("SELECT * FROM tasks WHERE run_id = ?", (run_id,))
        }
        return [rows[stage] for stage in self._plan(run_id)]

    def _active(self, run_id):
        return {
            r["kind"]: r
            for r in self.db.execute(
                "SELECT * FROM artifacts WHERE run_id=? AND stale=0", (run_id,)
            )
        }

    @staticmethod
    def _kinds(stage):
        return (
            ("positioning", "pricing", "capabilities") if stage == "content" else (OUTPUTS[stage],)
        )

    def _contract(self, decision_row_id, data):
        """Keep legacy history intact, but only enforce authenticated revisions."""
        saved = data.get("contract")
        if saved is None:
            return decision_contract.build(
                None, "dec-" + digest({"row": decision_row_id})[:16], {},
                data.get("claims", []), data.get("assumptions", []),
            )
        approval = data.get("operator_approval", {})
        if (
            saved["approval_status"] == "approved"
            and approval.get("contract_sha256") == digest(saved)
            and approval.get("principal") == saved["approved_by"]
            and str(approval.get("principal", "")).startswith("posix-uid:")
        ):
            return saved
        # Recover only structured operator inputs from the decision's original snapshot.
        inputs = {}
        for dependency in data.get("dependencies", []):
            field = dependency["field"]
            if field not in {"goal", "budget"}:
                continue
            row = self.db.execute(
                "SELECT value FROM evidence WHERE field=? AND revision=?",
                (field, dependency["revision"]),
            ).fetchone()
            if row:
                inputs[field] = json.loads(row["value"])
        effective = decision_contract.build(
            {field: saved[field] for field in decision_contract.FIELDS},
            saved["decision_id"], inputs, data.get("claims", []), saved["assumptions"],
        )
        return {**effective, "decision_revision": saved["decision_revision"]}

    def _event(self, run_id, stage, attempt, data):
        self.db.execute(
            "INSERT INTO events(run_id,stage,attempt,data) VALUES (?,?,?,?)",
            (run_id, stage, attempt, encode(data)),
        )

    def _set_task(self, run_id, stage, status, detail=None):
        self.db.execute(
            "UPDATE tasks SET status = ?, detail = ? WHERE run_id = ? AND stage = ?",
            (status, detail, run_id, stage),
        )

    def _claim(self, run_id, execution, retry, recover, *, preview=False):
        with self.transaction():
            run = self._run(run_id)
            if run["execution"] != execution:
                raise HarnessError("adapter execution mode differs from the stored run")
            self._refresh_market(run_id)
            run = self._run(run_id)
            tasks = {t["stage"]: t for t in self._tasks(run_id)}
            task = next(
                (
                    t
                    for t in tasks.values()
                    if t["status"] not in {"succeeded", "blocked"}
                    and all(
                        tasks[p]["status"] == "succeeded" for p in PARENTS[t["stage"]] if p in tasks
                    )
                ),
                None,
            )
            if task is None:
                return None
            stage, status = task["stage"], task["status"]
            if status == "running" and not recover:
                raise HarnessError("attempt is running; use explicit recovery after interruption")
            if status == "failed" and not retry:
                raise HarnessError("attempt failed; use explicit retry")
            inputs = self._inputs()
            pins = json.loads(run["registry"])
            base = {
                "project_id": self._project()["id"],
                "run_id": run_id,
                "stage": stage,
                "skill": pins[stage],
                "tool_policy": "deny_external_writes",
            }

            def request(fields, market_aware=True):
                if market_aware:
                    fields = sorted(set(fields) | (OPTIONAL_FIELDS & inputs.keys()))
                return {
                    **base,
                    "context": {f: inputs[f][0] for f in fields},
                    "evidence": [inputs[f][1] for f in fields],
                }

            if stage == "strategy":
                requests = [request(STRATEGY_FIELDS)]
                if "market_sources" in inputs:
                    requests[0]["evidence"].append(inputs["market_sources"][1])
                requests[0]["market_review"] = review(inputs.get("market_sources", ([], None))[0])
            else:
                decision = self.db.execute(
                    "SELECT id, data FROM decisions WHERE id = ?", (run["decision_id"],)
                ).fetchone()
                current = self._active(run_id)
                kinds = [kind for kind in self._kinds(stage) if kind not in current]
                required = {f for kind in kinds for f in DRAFT_FIELDS[kind]}
                missing = sorted(required - inputs.keys())
                if missing and preview:
                    return None
                if missing:
                    self._set_task(
                        run_id,
                        stage,
                        "blocked",
                        "missing evidence: " + ", ".join(missing),
                    )
                    return None
                requests = []
                for kind in kinds:
                    fields = set(DRAFT_FIELDS[kind])
                    handoffs = []
                    for upstream in HANDOFF_KINDS.get(stage, ()):
                        if upstream in current:
                            row = current[upstream]
                            artifact = json.loads(row["data"])
                            fields.update(
                                ref["field"]
                                for ref in artifact["dependencies"]
                                if ref["field"] in inputs
                            )
                            handoffs.append(
                                {
                                    "id": row["id"],
                                    "kind": upstream,
                                    "markdown": artifact["markdown"],
                                }
                            )
                    item = {
                        **request(sorted(fields - {"market_sources"}), kind not in PRODUCT_ONLY),
                        "artifact_kind": kind,
                    }
                    if handoffs:
                        item["handoffs"] = handoffs
                    if kind not in PRODUCT_ONLY:
                        if "market_sources" in inputs:
                            item["evidence"].append(inputs["market_sources"][1])
                    if decision and kind not in {"pricing", "capabilities"}:
                        saved = json.loads(decision["data"])
                        contract = self._contract(decision["id"], saved)
                        item["decision"] = {
                            "id": run["decision_id"],
                            "decision_id": contract["decision_id"],
                            "decision_revision": contract["decision_revision"],
                            "contract_sha256": digest(contract),
                            "contract": contract,
                            "recommendation": saved["recommendation"],
                        }
                    if kind not in PRODUCT_ONLY:
                        item["market_review"] = self._market()
                    requests.append(item)
            for item in requests:
                validate("task-input", item)
            attempt = task["attempt"] + 1
            if preview:
                return stage, attempt, requests
            self.db.execute(
                """
                UPDATE tasks SET status = 'running', attempt = ?, detail = NULL
                WHERE run_id = ? AND stage = ?
            """,
                (attempt, run_id, stage),
            )
            self._event(
                run_id,
                stage,
                attempt,
                {"status": "running", "input_digest": digest(requests)},
            )
            return stage, attempt, requests

    def _owns_attempt(self, run_id, stage, attempt):
        row = self.db.execute(
            "SELECT status, attempt FROM tasks WHERE run_id = ? AND stage = ?",
            (run_id, stage),
        ).fetchone()
        return row["status"] == "running" and row["attempt"] == attempt

    def step(self, run_id, adapter, *, retry=False, recover=False):
        claim = self._claim(run_id, adapter.execution, retry, recover)
        if claim is None:
            return self.status(run_id)
        stage, attempt, requests = claim
        try:
            results = []
            for item in requests:
                try:
                    result = adapter.execute(json.loads(encode(item)))
                finally:
                    receipt = getattr(adapter, "last_receipt", None)
                    if receipt is not None:
                        validate("host-receipt", receipt)
                        with self.transaction():
                            self._event(run_id, stage, attempt, {"host_receipt": receipt})
                if adapter.execution in {"model", "handoff"}:
                    result = decision_contract.normalize_host_draft(result)
                result = validate(
                    "strategy-result" if stage == "strategy" else "content-result", result
                )
                if adapter.execution in {"model", "handoff"} and "claims" in result:
                    result = {
                        **result,
                        "claims": [
                            {key: value for key, value in claim.items() if key != "review"}
                            for claim in result["claims"]
                        ],
                    }
                results.append(result)
            for req, result in zip(requests, results):
                market = req.get("market_review", {"citation_ids": [], "sources": []})
                claims = result.get("claims", [])
                citations = result.get("citations", [])
                if (
                    adapter.execution == "model"
                    and citations
                    and set(citations) != {claim["source_id"] for claim in claims}
                ):
                    raise HarnessError("market citations require exact claims")
                source_dependencies(market, claims, citations)
            checks = []
            for req, result in zip(requests, results):
                if "decision" not in req:
                    checks.append(None)
                    continue
                if result.get("constraint_refs") is None and adapter.execution == "fixture":
                    result["constraint_refs"] = decision_contract.declaration(
                        req["decision"]["contract"]
                    )
                outcome = decision_contract.check(
                    req["decision"]["contract"], result.get("constraint_refs")
                )
                if outcome["status"] in {"drifted", "stale_version", "not_declared"}:
                    detail = ", ".join(
                        f"{item['field']} {item['kind']}" for item in outcome["drift"]
                    )
                    raise HarnessError(
                        f"decision constraints {outcome['status']}: {detail}"
                    )
                checks.append(outcome)
            audits = []
            for req, result in zip(requests, results):
                market = req.get("market_review", {"citation_ids": [], "sources": []})
                text = result.get("recommendation") if stage == "strategy" else result.get("markdown")
                audit = audit_evidence(
                    market,
                    result.get("claims", []),
                    result.get("citations", []),
                    text,
                    execution=adapter.execution,
                    gaps=result.get("evidence_gaps", []),
                )
                audits.append(audit)
            if stage != "strategy" and any(
                req["artifact_kind"] != result["kind"] for req, result in zip(requests, results)
            ):
                raise HarnessError("adapter returned an unexpected artifact kind")
            if stage == "strategy":
                req, result = requests[0], results[0]
                built_contract = decision_contract.build(
                    result.get("contract"),
                    "dec-"
                    + digest(
                        {
                            "run": run_id,
                            "recommendation": result["recommendation"],
                            "goal": req["context"].get("goal"),
                        }
                    )[:16],
                    {
                        "goal": req["context"].get("goal"),
                        "budget": req["context"].get("budget"),
                    },
                    result.get("claims", []),
                    result.get("assumptions", []),
                )
        except Exception as exc:
            with self.transaction():
                if self._owns_attempt(run_id, stage, attempt):
                    receipt = getattr(adapter, "last_receipt", None) or {}
                    detail = (
                        str(exc)
                        if isinstance(exc, HarnessError)
                        else receipt.get("error_code") or type(exc).__name__
                    )
                    self._set_task(run_id, stage, "failed", detail)
                    self._event(run_id, stage, attempt, {"status": "failed", "error": detail})
            raise HarnessError(f"{stage} attempt failed; inspect status and retry") from None

        with self.transaction():
            if not self._owns_attempt(run_id, stage, attempt):
                raise HarnessError("attempt superseded; results discarded")
            for req, result, audit, check in zip(requests, results, audits, checks):
                refs = [
                    {key: item[key] for key in ("field", "revision")} for item in req["evidence"]
                ]
                data = {**result, "dependencies": refs, "execution": adapter.execution}
                data["evidence_audit"] = audit
                if stage == "strategy" or "decision" in req:
                    if not any(ref["field"] == "market_sources" for ref in refs):
                        refs.append({"field": "market_sources", "revision": 0})
                if "market_review" in req:
                    market = req["market_review"]
                    data["source_dependencies"] = source_dependencies(
                        market, result.get("claims", []), result.get("citations", [])
                    )
                    data["market_status"] = (
                        market["status"]
                        if result.get("claims") or result.get("citations")
                        else "needs_review"
                    )
                if stage == "strategy":
                    market = req["market_review"]
                    data.update(
                        citation_ids=result.get("citations", []),
                        eligible_citation_ids=market["citation_ids"],
                        contradictions=market["contradictions"],
                    )
                    data.pop("citations", None)
                    data["contract"] = built_contract
                    ident = self.db.execute(
                        "INSERT INTO decisions(run_id,data) VALUES (?,?)",
                        (run_id, encode(validate("decision", data))),
                    ).lastrowid
                    self.db.execute("UPDATE runs SET decision_id = ? WHERE id = ?", (ident, run_id))
                    self._set_task(run_id, "content", "queued")
                else:
                    if "decision" in req:
                        data["decision_id"] = req["decision"]["id"]
                        data["decision_revision"] = req["decision"]["decision_revision"]
                        data["decision_contract_sha256"] = req["decision"]["contract_sha256"]
                    else:
                        data.pop("constraint_refs", None)
                    if check is not None:
                        data["constraint_check"] = {
                            key: check[key]
                            for key in ("status", "decision_revision", "drift", "proposals")
                        }
                    if req.get("handoffs"):
                        data["handoff_ids"] = [handoff["id"] for handoff in req["handoffs"]]
                    data.update(status="draft", sha256=digest(result["markdown"]))
                    self.db.execute(
                        "INSERT INTO artifacts(run_id,kind,data) VALUES (?,?,?)",
                        (run_id, result["kind"], encode(validate("artifact", data))),
                    )
            self._set_task(run_id, stage, "succeeded")
            self._event(run_id, stage, attempt, {"status": "succeeded", "calls": len(requests)})
        return self.status(run_id)

    def status(self, run_id):
        with self.transaction():
            self._refresh_market(run_id)
            run = self._run(run_id)
            project = self._project()
            context = validate(
                "context",
                {
                    "project_id": project["id"],
                    "revision": project["revision"],
                    "values": {k: v for k, (v, _) in self._inputs().items()},
                },
            )
            tasks = [
                validate(
                    "task-state",
                    {k: v for k, v in dict(t).items() if k != "run_id" and v is not None},
                )
                for t in self._tasks(run_id)
            ]
            decisions = [
                {"id": r["id"], **json.loads(r["data"])}
                for r in self.db.execute(
                    "SELECT id,data FROM decisions WHERE run_id = ? ORDER BY id",
                    (run_id,),
                )
            ]
            for item in decisions:
                if item["id"] == run["decision_id"] and "contract" in item:
                    item["contract"] = self._contract(item["id"], item)
            artifacts = []
            for row in self.db.execute(
                "SELECT * FROM artifacts WHERE run_id = ? ORDER BY id", (run_id,)
            ):
                artifact = json.loads(row["data"])
                if row["stale"]:
                    artifact["status"] = "stale"
                artifacts.append({"id": row["id"], **artifact})
            return {
                "run_id": run_id,
                "execution": run["execution"],
                "context": context,
                "schema_version": 1,
                "workflow_version": 2 if run["plan"] else 1,
                "plan": self._plan(run_id),
                "history": [
                    {**dict(row), "data": json.loads(row["data"])}
                    for row in self.db.execute(
                        "SELECT stage,attempt,data FROM events WHERE run_id=? ORDER BY id",
                        (run_id,),
                    )
                ],
                "skill_pins": json.loads(run["registry"]),
                "tasks": tasks,
                "decisions": decisions,
                "evidence": [
                    json.loads(r["data"])
                    for r in self.db.execute("SELECT data FROM evidence ORDER BY revision, field")
                ],
                "active_decision_id": run["decision_id"],
                "artifacts": artifacts,
            }
