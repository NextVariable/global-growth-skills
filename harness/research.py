"""Local source registry checks; no network lookup or semantic truth scoring."""

from datetime import date
from urllib.parse import urlsplit

from .contracts import HarnessError, validate


def review(sources, today=None):
    validate("source-list", sources)
    today = today or date.today()
    ids = set()
    positions = {}
    records = []
    for row in sources:
        ident = row["id"]
        if ident in ids:
            raise HarnessError("duplicate source ID")
        ids.add(ident)
        url = urlsplit(row["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise HarnessError(
                "source locator requires an HTTPS URL without credentials"
            )
        try:
            observed = date.fromisoformat(row["observed_on"])
            expiry = date.fromisoformat(row["valid_until"])
        except ValueError:
            raise HarnessError("source date must be ISO YYYY-MM-DD") from None
        if observed > today or expiry < observed:
            raise HarnessError("invalid source date range")
        status = (
            "stale"
            if expiry < today
            else "unverified"
            if row["kind"] != "observation"
            else "reviewable"
        )
        records.append({**row, "status": status})
        if status == "reviewable":
            positions.setdefault(row["claim_key"], set()).add(row["stance"])
    conflicts = sorted(key for key, stances in positions.items() if len(stances) > 1)
    citations = [
        row["id"]
        for row in records
        if row["status"] == "reviewable" and row["claim_key"] not in conflicts
    ]
    return {
        "sources": records,
        "contradictions": conflicts,
        "citation_ids": citations,
        "status": "needs_review" if conflicts or not citations else "sources_available",
    }
