"""Source eligibility, observed excerpts, and exact citation validation."""

from datetime import date, datetime, timezone
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from .contracts import HarnessError, digest, validate

EXPIRING_DAYS = 30

INJECTION_PATTERNS = {
    "ignore_instructions": r"ignore\s+(?:all\s+|any\s+)?(?:previous|prior|above)\s+(?:instructions?|prompts?|rules?)",
    "disregard_instructions": r"disregard\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier)",
    "system_prompt": r"system\s*(?:prompt|message|instruction)\s*[:：]",
    "role_override": r"you\s+are\s+now\s+(?:a|an|the)\b",
    "chat_template_marker": r"<\|?\s*(?:system|assistant|user)\s*\|?>",
    "begin_instructions": r"\bbegin\s+(?:system|instructions?)\b",
    "credential_request": r"\b(?:send|exfiltrate|upload|reveal)\b.{0,60}\b(?:credentials?|api\s*keys?|tokens?|customer\s+list|密钥|私钥)\b",
    "approval_bypass": r"\b(?:approve|execute|publish|delete|transfer)\b.{0,60}\b(?:without|bypass|skip)\b.{0,30}\b(?:approval|review|consent)\b",
}

TRACKING_PARAMS = re.compile(r"^(?:utm_|ref$|source$|fbclid$|gclid$)")


def injection_flags(text):
    return sorted(
        name for name, pattern in INJECTION_PATTERNS.items() if re.search(pattern, text, re.I)
    )


def freshness(row, today):
    expiry = date.fromisoformat(row["valid_until"])
    if expiry < today:
        return "expired"
    if (expiry - today).days <= EXPIRING_DAYS:
        return "expiring"
    return "fresh"


def _canonical_url(row):
    url = urlsplit(row["url"])
    query = [
        (key, value)
        for key, value in parse_qsl(url.query, keep_blank_values=True)
        if not TRACKING_PARAMS.match(key)
    ]
    return (
        (url.hostname or "").casefold(),
        url.path.rstrip("/") or "/",
        urlencode(sorted(query)),
        row["claim_key"],
        row["stance"],
    )


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
        flags = injection_flags(row["excerpt"])
        if row.get("capture"):
            from .github_research import PROVIDER as GITHUB_PROVIDER, excerpt

            capture = row["capture"]
            facts = capture["facts"]
            if capture.get("provider") == GITHUB_PROVIDER:
                expected_id = "gh-" + digest(facts["full_name"].casefold())[:20]
                if (
                    row["excerpt"] != excerpt(facts)
                    or row["url"] != "https://github.com/" + facts["full_name"]
                    or row["id"] != expected_id
                    or row["claim_key"] != expected_id
                ):
                    raise HarnessError("capture does not match the normalized GitHub evidence")
            else:
                from .web_research import verify_capture

                verify_capture(row)
        if status == "reviewable" and row.get("capture") and flags:
            status = "blocked_injection"
        key = _canonical_url(row)
        if status == "reviewable":
            if key in observations:
                status = "duplicate"
            observations.add(key)
        records.append({**row, "status": status, "injection_flags": flags, "freshness": freshness(row, today)})
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
        "freshness": {
            "fresh": sum(row["freshness"] == "fresh" for row in records),
            "expiring": sum(row["freshness"] == "expiring" for row in records),
            "expired": sum(row["freshness"] == "expired" for row in records),
        },
    }


def source_fingerprint(row):
    return digest(
        {
            key: row[key]
            for key in ("id", "claim_key", "url", "kind", "stance", "excerpt")
        }
    )


def source_dependencies(market, claims, citations=()):
    eligible = set(market["citation_ids"])
    refs = set(citations) | {claim["source_id"] for claim in claims}
    if not refs <= eligible:
        raise HarnessError("citation is missing, stale or contradicted")
    by_id = {row["id"]: row for row in market["sources"]}
    for claim in claims:
        quote = re.sub(r"\s+", " ", claim["quote"]).strip()
        excerpt = re.sub(r"\s+", " ", by_id[claim["source_id"]]["excerpt"]).strip()
        if not quote or quote not in excerpt:
            raise HarnessError("market claim does not match its cited excerpt")
    return {ident: source_fingerprint(by_id[ident]) for ident in sorted(refs or eligible)}


def prompt_review(market):
    """Pass allow-listed captured observations; retain general text for human review."""
    return {
        **market,
        "sources": [
            {
                key: row[key]
                for key in ("id", "excerpt", "status", "observed_on", "valid_until", "freshness")
            }
            for row in market["sources"]
            if row["id"] in market["citation_ids"]
            and row.get("capture")
            and not row.get("injection_flags")
        ],
    }


def dependencies_changed(market, saved):
    """Only the exact cited sources matter; unrelated sources must not stale drafts."""
    by_id = {row["id"]: row for row in market["sources"]}
    eligible = set(market["citation_ids"])
    for ident, fingerprint in saved.items():
        row = by_id.get(ident)
        if row is None or ident not in eligible or row["status"] != "reviewable":
            return True
        if source_fingerprint(row) != fingerprint:
            return True
    return False


# These patterns flag candidate claims for review; they do not grade general prose.
PROSE_PATTERNS = {
    "repository_metric_in_prose": r"\b\d[\d,.]*\s*(?:k|m)?\s*(?:stars?|forks?|stargazers)\b|\d[\d,.]*\s*(?:星标|星級|分叉)",
    "market_size_in_prose": r"(?:market size|(?:the )?TAM|市场规模)\s*(?:is|of|:|：|为)?\s*[$€£¥]\s*\d",
    "adoption_count_in_prose": r"\b\d[\d,.]*\s*(?:k|m|million|billion)?\s*(?:active|paying)\s+(?:users|customers)\b",
    "percentage_claim_in_prose": r"\b\d+(?:\.\d+)?\s*%\s*(?:of|increase|decrease|growth|conversion|churn|retention)",
    "cited_research_in_prose": r"\b(?:according to|per the|a \d{4} (?:report|survey|study)|(?:report|survey|study) (?:found|shows?))\b",
    "forecast_in_prose": r"\b(?:forecast|projected to|expected to reach|CAGR)\b",
}


def prose_review(text):
    return [name for name, pattern in PROSE_PATTERNS.items() if re.search(pattern, text, re.I)]
