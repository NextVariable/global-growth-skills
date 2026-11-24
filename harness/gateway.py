"""Read-only evidence bridge and single-use, local operator grants for mock writes."""

from contextlib import nullcontext
import json
import os
import time

from .contracts import HarnessError, digest, encode, validate
from .research import review
from .github_research import PROVIDER, fetch
from .hn_research import PROVIDER as HN_PROVIDER, fetch as fetch_hn
from .web_research import PROVIDER as WEB_PROVIDER, fetch as fetch_web


OPERATION_ACCESS = {
    "publish": "external_write",
    "outreach": "external_write",
    "crm_update": "external_write",
    "ad_spend": "financial_action",
}


class MockExecutor:
    def __init__(self):
        self.calls = 0

    def execute(self, operation):
        self.calls += 1
        return {
            "executor": "mock",
            "status": "confirmed",
            "target": operation["target"],
        }


class Gateway:
    """The caller must be a trusted local operator. Never expose grants to an agent."""

    def __init__(self, harness, *, readers=None, clock=time.time):
        self.harness = harness
        self.readers = {
            PROVIDER: fetch,
            WEB_PROVIDER: fetch_web,
            HN_PROVIDER: fetch_hn,
            **(readers or {}),
        }
        self.clock = clock
        self.mock = MockExecutor()

    def _actor(self):
        if not hasattr(os, "getuid"):
            raise HarnessError("mock approvals require a POSIX local operator identity")
        return f"uid:{os.getuid()}"

    def _event(self, ident, event, data):
        self.harness.db.execute(
            "INSERT INTO tool_events(operation_id,event,data) VALUES (?,?,?)",
            (ident, event, encode(data)),
        )

    def _verify(self, operation):
        validate("operation", operation)
        if operation["project_id"] != self.harness._project()["id"]:
            raise HarnessError("operation belongs to a different project")
        return operation["id"]

    def _digest(self, operation):
        return digest(
            {
                "operation": operation,
                "context_revision": self.harness._project()["revision"],
            }
        )

    def prepare(self, operation):
        with self.harness.transaction():
            self._verify(operation)
            return {
                "access": OPERATION_ACCESS[operation["kind"]],
                "mode": "draft_prepare",
                "digest": self._digest(operation),
                "executor": "mock_only",
            }

    def research(self, query, provider=PROVIDER):
        # Snapshot revision before the read. A concurrent change must not be overwritten.
        with self.harness.transaction():
            revision = self.harness._project()["revision"]
        records = self.read(provider, query)
        with self.harness.transaction():
            if self.harness._project()["revision"] != revision:
                raise HarnessError("context changed during research; retry the read")
            sources = self.harness._inputs().get("market_sources", ([], None))[0]
            merged = {row["id"]: row for row in sources}
            for row in records:
                previous = merged.get(row["id"])
                if previous and previous.get("capture", {}).get("provider") != provider:
                    raise HarnessError("capture ID collides with an operator source")
                merged[row["id"]] = row
            combined = list(merged.values())
            market = review(combined)
            change = self.harness._apply_patch({"market_sources": combined}) if records else {}
        return {
            "provider": provider,
            "access": "read_only",
            "query": query,
            "status": "retrieved" if records else "no_results",
            "retrieved": records,
            "source_review": market,
            **change,
        }

    def approve(self, operation, ttl):
        with self.harness.transaction():
            ident = self._verify(operation)
            if type(ttl) is not int or not 1 <= ttl <= 3600:
                raise HarnessError("approval TTL must be 1–3600 seconds")
            actor = self._actor()
            if self.harness.db.execute("SELECT 1 FROM approvals WHERE id=?", (ident,)).fetchone():
                raise HarnessError("operation already has an approval history")
            expires = int(self.clock()) + ttl
            self.harness.db.execute(
                "INSERT INTO approvals VALUES (?,?,?,?,'approved')",
                (ident, actor, self._digest(operation), expires),
            )
            self._event(
                ident,
                "approved",
                {"actor": actor, "expires": expires, "digest": self._digest(operation)},
            )

    def revoke(self, ident):
        with self.harness.transaction():
            result = self.harness.db.execute(
                "UPDATE approvals SET state='revoked' WHERE id=? AND actor=? AND state='approved'",
                (ident, self._actor()),
            )
            if result.rowcount != 1:
                raise HarnessError("no revocable approval for this operator")
            self._event(ident, "revoked", {})

    def write(self, operation):
        with self.harness.transaction():
            ident = self._verify(operation)
            grant = self.harness.db.execute(
                "SELECT * FROM approvals WHERE id=?", (ident,)
            ).fetchone()
            if (
                not grant
                or grant["actor"] != self._actor()
                or grant["state"] != "approved"
                or grant["operation_digest"] != self._digest(operation)
                or grant["expires"] <= self.clock()
            ):
                raise HarnessError("write denied: exact unexpired unused approval required")
            self.harness.db.execute("UPDATE approvals SET state='consumed' WHERE id=?", (ident,))
            self._event(
                ident,
                "outcome_unknown",
                {"executor": "mock", "digest": self._digest(operation)},
            )
        try:
            receipt = self.mock.execute(operation)
            validate("mock-receipt", receipt)
            if receipt["target"] != operation["target"]:
                raise HarnessError("receipt target mismatch")
        except Exception:
            raise HarnessError("mock result unknown; do not retry this operation ID") from None
        with self.harness.transaction():
            self._event(ident, "confirmed", receipt)
        return receipt

    def read(self, tool, query):
        if tool not in self.readers:
            raise HarnessError("source is not a registered read-only provider")
        validate("run-id", tool)
        try:
            records = self.readers[tool](query)
            review(records)
        except Exception as exc:
            with self.harness.transaction():
                self._event(tool, "read_failed", {"query_digest": digest(query)})
            if self.readers[tool] is fetch and isinstance(exc, HarnessError):
                raise
            raise HarnessError("read-only provider failed or returned invalid evidence") from None
        with self.harness.transaction():
            self._event(
                tool,
                "read_confirmed",
                {"query_digest": digest(query), "source_count": len(records)},
            )
        return records

    def receipts(self):
        scope = nullcontext() if self.harness.db.in_transaction else self.harness.transaction()
        with scope:
            return [
                {**dict(row), "data": json.loads(row["data"])}
                for row in self.harness.db.execute(
                    "SELECT operation_id,event,data FROM tool_events ORDER BY id"
                )
            ]
