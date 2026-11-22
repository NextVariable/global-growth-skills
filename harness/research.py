"""Source eligibility, observed excerpts, and exact citation validation."""

from datetime import date, datetime, timezone
import re
from urllib.parse import urlsplit

from .contracts import HarnessError, digest, validate
from .github_research import excerpt


def review(sources, today=None):
    validate("source-list", sources)
    today = today or datetime.now(timezone.utc).date()
    ids = set()
    positions = {}
    records = []
    observations = set()
    for row in sources:
        ident = row["id"]
        if ident in ids:
            raise HarnessError("duplicate source ID")
        ids.add(ident)
        url = urlsplit(row["url"])
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise HarnessError("source locator requires an HTTPS URL without credentials")
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
        if row.get("capture"):
            facts = row["capture"]["facts"]
            expected_id = "gh-" + digest(facts["full_name"].casefold())[:20]
            if (
                row["excerpt"] != excerpt(facts)
                or row["url"] != "https://github.com/" + facts["full_name"]
                or row["id"] != expected_id
                or row["claim_key"] != expected_id
            ):
                raise HarnessError("capture does not match the normalized GitHub evidence")
        key = (url.hostname, url.path.rstrip("/"), url.query, row["claim_key"], row["stance"])
        if status == "reviewable":
            if key in observations:
                status = "duplicate"
            observations.add(key)
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


def source_dependencies(market, claims, citations=()):
    eligible = set(market["citation_ids"])
    refs = set(citations) | {claim["source_id"] for claim in claims}
    if not refs <= eligible:
        raise HarnessError("citation is missing, stale or contradicted")
    by_id = {row["id"]: row for row in market["sources"]}
    for claim in claims:
        if claim["quote"] != by_id[claim["source_id"]]["excerpt"]:
            raise HarnessError("market claim does not match its cited excerpt")
    return {
        ident: digest(
            {
                key: by_id[ident][key]
                for key in ("id", "claim_key", "url", "kind", "stance", "excerpt")
            }
        )
        for ident in sorted(refs or eligible)
    }


def prompt_review(market):
    """Pass allow-listed GitHub observations; retain general source text for human review."""
    return {
        **market,
        "sources": [
            {key: row[key] for key in ("id", "excerpt", "status")}
            for row in market["sources"]
            if row["id"] in market["citation_ids"] and row.get("capture")
        ],
    }


def dependencies_changed(market, saved):
    observed = source_dependencies(market, [])
    return any(observed.get(ident) != fingerprint for ident, fingerprint in saved.items())


# These patterns flag candidate claims for review; they do not grade general prose.
PROSE_PATTERNS = {
    "repository_metric_in_prose": r"\b\d[\d,.]*\s*(?:k|m)?\s*(?:stars?|forks?|stargazers)\b|\d[\d,.]*\s*(?:星标|星級|分叉)",
    "market_size_in_prose": r"(?:market size|(?:the )?TAM|市场规模)\s*(?:is|of|:|：|为)?\s*[$€£¥]\s*\d",
    "adoption_count_in_prose": r"\b\d[\d,.]*\s*(?:k|m|million|billion)?\s*(?:active|paying)\s+(?:users|customers)\b",
}


def prose_review(text):
    return [name for name, pattern in PROSE_PATTERNS.items() if re.search(pattern, text, re.I)]
