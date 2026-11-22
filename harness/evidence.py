"""Claim-to-evidence mapping, freshness and missing-evidence diagnostics."""

from datetime import date
import re

from .contracts import HarnessError, digest
from .research import PROSE_PATTERNS, freshness, prose_review

EXPIRING_DAYS = 30


def normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def _claim_id(source_id, quote, text):
    return "clm-" + digest(
        {"source_id": source_id, "quote": normalize(quote), "text": normalize(text or "")}
    )[:16]


def build_claim_map(market, claims, citations=(), today=None):
    """Map every claim to an eligible source and a verbatim support fragment."""
    today = today or date.today()
    eligible = set(market["citation_ids"])
    by_id = {row["id"]: row for row in market["sources"]}
    citations = list(citations or [])
    if len(set(citations)) != len(citations):
        raise HarnessError("citation list contains duplicates")
    if not set(citations) <= {claim["source_id"] for claim in claims}:
        raise HarnessError("every citation must belong to a mapped claim")
    if not set(citations) <= eligible:
        raise HarnessError("citation is missing, stale or contradicted")

    mapped = []
    seen = set()
    duplicates = 0
    for claim in claims:
        ident = claim["source_id"]
        row = by_id.get(ident)
        if row is None:
            raise HarnessError("claim refers to an unknown source")
        if ident not in eligible or row["status"] != "reviewable":
            raise HarnessError("claim refers to a source that is not eligible evidence")
        quote = normalize(claim["quote"])
        excerpt = normalize(row["excerpt"])
        if not quote or quote not in excerpt:
            raise HarnessError("claim quote is not a verbatim fragment of its source excerpt")
        text = claim.get("text")
        if text is not None and not normalize(text):
            raise HarnessError("claim text must not be blank")
        key = (ident, quote)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        mapped.append(
            {
                "claim_id": _claim_id(ident, quote, text),
                "source_id": ident,
                "quote": quote,
                "text": normalize(text) if text else None,
                "support": "exact_excerpt" if quote == excerpt else "excerpt_fragment",
                "claim_key": row["claim_key"],
                "observed_on": row["observed_on"],
                "valid_until": row["valid_until"],
                "freshness": freshness(row, today),
                "stance": row["stance"],
            }
        )
    return {
        "claims": mapped,
        "duplicates_removed": duplicates,
        "source_ids": sorted({item["source_id"] for item in mapped}),
        "freshness": {
            item["source_id"]: item["freshness"]
            for item in mapped
        },
    }


def audit_evidence(market, claims, citations, text, *, execution, today=None, gaps=()):
    """Combine exact claim validation with visible prose and source risk."""
    market = market or {"citation_ids": [], "sources": [], "contradictions": [], "status": "needs_review"}
    today = today or date.today()
    mapped = build_claim_map(market, claims, citations, today)
    prose_flags = prose_review(text)
    eligible = list(market["citation_ids"])
    injection = sorted(
        {
            flag
            for row in market["sources"]
            for flag in row.get("injection_flags", [])
        }
    )
    missing_claims = bool(eligible) and not claims
    if not market["sources"]:
        status = "not_applicable"
    elif not eligible:
        status = "no_eligible_sources"
    elif missing_claims:
        status = "missing_claims"
    elif prose_flags:
        status = "partial"
    else:
        status = "verified"

    diagnostics = list(gaps or [])
    if missing_claims:
        diagnostics.append("No structured claim uses the eligible sources supplied for this stage.")
    if prose_flags:
        diagnostics.append(
            "Unmapped external-fact patterns in prose: " + ", ".join(prose_flags)
        )
    expiring = sorted(
        source_id for source_id, label in mapped["freshness"].items() if label != "fresh"
    )
    if expiring:
        diagnostics.append("Evidence expires within 30 days: " + ", ".join(expiring))
    if injection:
        diagnostics.append("Source text contains instruction-like content: " + ", ".join(injection))

    return {
        "status": status,
        "execution": execution,
        "eligible_source_count": len(eligible),
        "missing_claims": missing_claims,
        "prose_flags": prose_flags,
        "claims": mapped["claims"],
        "duplicates_removed": mapped["duplicates_removed"],
        "source_ids": mapped["source_ids"],
        "freshness": mapped["freshness"],
        "injection_flags": injection,
        "evidence_gaps": diagnostics,
    }


def requires_claim_mapping(audit):
    """A model run with eligible sources must map at least one claim."""
    return audit["execution"] == "model" and audit["status"] == "missing_claims"


def prose_pattern_names():
    return sorted(PROSE_PATTERNS)
