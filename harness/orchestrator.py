"""A two-stage workflow with durable checkpoints and per-draft invalidation."""

import json

from .contracts import HarnessError, digest, encode, validate
from .registry import skill_registry
from .store import Store

STRATEGY_FIELDS = ("product", "audience", "goal")
DRAFT_FIELDS = {
    "positioning": STRATEGY_FIELDS,
    "pricing": ("price",),
    "capabilities": ("capabilities",),
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
        return {row["field"]: (json.loads(row["value"]), json.loads(row["data"])) for row in rows}

    def _save_evidence(self, field, revision, value):
        evidence = validate("evidence", {
            "field": field, "revision": revision, "source": "operator_input", "sha256": digest(value)
        })
        self.db.execute("INSERT INTO evidence VALUES (?, ?, ?, ?)",
                        (field, revision, encode(value), encode(evidence)))

    def initialize(self, data):
        validate("project-input", data)
        with self.transaction():
            if self.db.execute("SELECT 1 FROM project").fetchone():
                raise HarnessError("database already has a project")
            self.db.execute("INSERT INTO project VALUES (?, 1)", (data["project_id"],))
            for field, value in data["values"].items():
                self._save_evidence(field, 1, value)

    def update(self, patch):
        validate("context-patch", patch)
        with self.transaction():
            project, inputs = self._project(), self._inputs()
            changes = {
                field: value for field, value in patch.items()
                if field not in inputs or encode(value) != encode(inputs[field][0])
            }
            revision = project["revision"]
            if not changes:
                return {"revision": revision, "stale_artifact_ids": []}
            revision += 1
            self.db.execute("UPDATE project SET revision = ?", (revision,))
            for field, value in changes.items():
                self._save_evidence(field, revision, value)
            stale = []
            for row in self.db.execute("SELECT id, data FROM artifacts WHERE stale = 0").fetchall():
                deps = json.loads(row["data"])["dependencies"]
                if any(ref["field"] in changes for ref in deps):
                    stale.append(row["id"])
                    self.db.execute("UPDATE artifacts SET stale = 1 WHERE id = ?", (row["id"],))
            if changes.keys() & set(STRATEGY_FIELDS):
                self.db.execute("UPDATE runs SET decision_id = NULL")
                self.db.execute("UPDATE tasks SET status = 'queued', detail = NULL WHERE stage = 'strategy'")
                self.db.execute("UPDATE tasks SET status = 'pending', detail = NULL WHERE stage = 'content'")
            else:
                self.db.execute("""
                    UPDATE tasks SET status = 'queued', detail = NULL
                    WHERE stage = 'content' AND status != 'pending'
                """)
            return {"revision": revision, "stale_artifact_ids": stale}

    def start(self, run_id, execution="fixture"):
        validate("run-id", run_id)
        if execution not in {"fixture", "model"}:
            raise HarnessError("unsupported execution mode")
        pins = encode(skill_registry())
        with self.transaction():
            self._project()
            existing = self.db.execute("SELECT execution FROM runs WHERE id = ?", (run_id,)).fetchone()
            if existing:
                if existing["execution"] != execution:
                    raise HarnessError("run already uses another execution mode")
                return
            self.db.execute("INSERT INTO runs VALUES (?, ?, ?, NULL)", (run_id, pins, execution))
            self.db.executemany("INSERT INTO tasks VALUES (?, ?, ?, 0, NULL)",
                                [(run_id, "strategy", "queued"), (run_id, "content", "pending")])

    def _run(self, run_id):
        run = self.db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            raise HarnessError("unknown run")
        return run

    def _tasks(self, run_id):
        return self.db.execute("SELECT * FROM tasks WHERE run_id = ? ORDER BY stage DESC", (run_id,))

    def _set_task(self, run_id, stage, status, detail=None):
        self.db.execute("UPDATE tasks SET status = ?, detail = ? WHERE run_id = ? AND stage = ?",
                        (status, detail, run_id, stage))

    def _claim(self, run_id, execution, retry, recover):
        with self.transaction():
            run = self._run(run_id)
            if run["execution"] != execution:
                raise HarnessError("adapter execution mode differs from the stored run")
            task = next((t for t in self._tasks(run_id) if t["status"] != "succeeded"), None)
            if task is None:
                return None
            stage, status = task["stage"], task["status"]
            if status == "running" and not recover:
                raise HarnessError("attempt is running; use explicit recovery after interruption")
            if status == "failed" and not retry:
                raise HarnessError("attempt failed; use explicit retry")
            if status == "blocked":
                return None
            inputs = self._inputs()
            pins = json.loads(run["registry"])
            base = {"project_id": self._project()["id"], "run_id": run_id, "stage": stage,
                    "skill": pins[stage], "tool_policy": "deny_external_writes"}

            def request(fields):
                return {**base, "context": {f: inputs[f][0] for f in fields},
                        "evidence": [inputs[f][1] for f in fields]}

            if stage == "strategy":
                requests = [request(STRATEGY_FIELDS)]
            else:
                decision = self.db.execute("SELECT data FROM decisions WHERE id = ?",
                                           (run["decision_id"],)).fetchone()
                if decision is None:
                    raise HarnessError("content requires a committed strategy decision")
                current = {row["kind"] for row in self.db.execute(
                    "SELECT kind FROM artifacts WHERE run_id = ? AND stale = 0", (run_id,))}
                required = {f for kind, fields in DRAFT_FIELDS.items() if kind not in current for f in fields}
                missing = sorted(required - inputs.keys())
                if missing:
                    self._set_task(run_id, stage, "blocked", "missing evidence: " + ", ".join(missing))
                    return None
                requests = []
                for kind, fields in DRAFT_FIELDS.items():
                    if kind in current:
                        continue
                    item = {**request(fields), "artifact_kind": kind}
                    if kind == "positioning":
                        item["decision"] = {"id": run["decision_id"],
                                            "recommendation": json.loads(decision["data"])["recommendation"]}
                    requests.append(item)
            for item in requests:
                validate("task-input", item)
            attempt = task["attempt"] + 1
            self.db.execute("""
                UPDATE tasks SET status = 'running', attempt = ?, detail = NULL
                WHERE run_id = ? AND stage = ?
            """, (attempt, run_id, stage))
            return stage, attempt, requests

    def _owns_attempt(self, run_id, stage, attempt):
        row = self.db.execute("SELECT status, attempt FROM tasks WHERE run_id = ? AND stage = ?",
                              (run_id, stage)).fetchone()
        return row["status"] == "running" and row["attempt"] == attempt

    def step(self, run_id, adapter, *, retry=False, recover=False):
        claim = self._claim(run_id, adapter.execution, retry, recover)
        if claim is None:
            return self.status(run_id)
        stage, attempt, requests = claim
        try:
            results = [validate(f"{stage}-result", adapter.execute(json.loads(encode(item)))) for item in requests]
            if stage == "content" and any(
                req["artifact_kind"] != result["kind"] for req, result in zip(requests, results)
            ):
                raise HarnessError("adapter returned an unexpected artifact kind")
        except Exception as exc:
            with self.transaction():
                if self._owns_attempt(run_id, stage, attempt):
                    detail = "invalid adapter result" if isinstance(exc, HarnessError) else type(exc).__name__
                    self._set_task(run_id, stage, "failed", detail)
            raise HarnessError(f"{stage} attempt failed; inspect status and retry") from None

        with self.transaction():
            if not self._owns_attempt(run_id, stage, attempt):
                raise HarnessError("attempt superseded; results discarded")
            for req, result in zip(requests, results):
                refs = [{key: item[key] for key in ("field", "revision")} for item in req["evidence"]]
                data = {**result, "dependencies": refs, "execution": adapter.execution}
                if stage == "strategy":
                    ident = self.db.execute("INSERT INTO decisions(run_id,data) VALUES (?,?)",
                                            (run_id, encode(validate("decision", data)))).lastrowid
                    self.db.execute("UPDATE runs SET decision_id = ? WHERE id = ?", (ident, run_id))
                    self._set_task(run_id, "content", "queued")
                else:
                    if "decision" in req:
                        data["decision_id"] = req["decision"]["id"]
                    data.update(status="draft", sha256=digest(result["markdown"]))
                    self.db.execute("INSERT INTO artifacts(run_id,kind,data) VALUES (?,?,?)",
                                    (run_id, result["kind"], encode(validate("artifact", data))))
            self._set_task(run_id, stage, "succeeded")
        return self.status(run_id)

    def status(self, run_id):
        with self.transaction():
            run = self._run(run_id)
            project = self._project()
            context = validate("context", {"project_id": project["id"], "revision": project["revision"],
                                           "values": {k: v for k, (v, _) in self._inputs().items()}})
            tasks = [validate("task-state", {k: v for k, v in dict(t).items()
                                           if k != "run_id" and v is not None}) for t in self._tasks(run_id)]
            decisions = [{"id": r["id"], **json.loads(r["data"])} for r in self.db.execute(
                "SELECT id,data FROM decisions WHERE run_id = ? ORDER BY id", (run_id,))]
            artifacts = []
            for row in self.db.execute("SELECT * FROM artifacts WHERE run_id = ? ORDER BY id", (run_id,)):
                artifact = json.loads(row["data"])
                if row["stale"]:
                    artifact["status"] = "stale"
                artifacts.append({"id": row["id"], **artifact})
            return {"run_id": run_id, "execution": run["execution"], "context": context,
                    "schema_version": 1, "workflow_version": 1,
                    "skill_pins": json.loads(run["registry"]), "tasks": tasks, "decisions": decisions,
                    "evidence": [json.loads(r["data"]) for r in self.db.execute(
                        "SELECT data FROM evidence ORDER BY revision, field")],
                    "active_decision_id": run["decision_id"], "artifacts": artifacts}
