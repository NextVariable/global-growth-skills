"""Claim-to-evidence mapping, freshness and missing-evidence diagnostics.

A verbatim quote proves only that the text appears in the source excerpt. It
does not prove that a draft claim follows from that text. Semantic support is
therefore recorded separately and stays ``unverified`` until a named model or
human review supplies a verdict.
"""

from datetime import datetime, timezone
import re

from .contracts import HarnessError, digest
from .research import PROSE_PATTERNS, freshness, prose_review

REVIEWERS = {"model", "human"}
VERDICTS = {"supported", "rejected", "uncertain"}
UNCERTAINTY = {"low", "medium", "high"}
REVIEW_FIELDS = {"reviewer", "verdict", "rationale", "uncertainty"}
REVIEW_OPTIONAL = {"model"}


def normalize(text):
    return re.sub(r"\s+", " ", text).strip()


def _claim_id(source_id, quote, text):
    return "clm-" + digest(
        {"source_id": source_id, "quote": normalize(quote), "text": normalize(text or "")}
    )[:16]


def _review(claim):
    """Validate an optional semantic review record and return (review, state)."""
    review = claim.get("review")
    if review is None:
        return None, "unverified"
    if not isinstance(review, dict):
        raise HarnessError("claim review must be an object")
    if set(review) - REVIEW_FIELDS - REVIEW_OPTIONAL or not REVIEW_FIELDS <= set(review):
        raise HarnessError(
            "claim review requires reviewer, verdict, rationale and uncertainty"
        )
    if review["reviewer"] not in REVIEWERS:
        raise HarnessError("claim review reviewer must be model or human")
    if review["reviewer"] == "model":
        if not isinstance(review.get("model"), str) or not normalize(review["model"]):
            raise HarnessError("model claim review must name the reviewing model")
    elif "model" in review:
        raise HarnessError("human claim review must not name a model")
    if review["verdict"] not in VERDICTS:
        raise HarnessError("claim review verdict must be supported, rejected or uncertain")
    if review["uncertainty"] not in UNCERTAINTY:
        raise HarnessError("claim review uncertainty must be low, medium or high")
    rationale = review["rationale"]
    if not isinstance(rationale, str) or not normalize(rationale):
        raise HarnessError("claim review requires a non-blank rationale")
    if len(rationale) > 2000:
        raise HarnessError("claim review rationale exceeds 2000 characters")
    recorded = {
        "reviewer": review["reviewer"],
        "verdict": review["verdict"],
        "rationale": normalize(rationale),
        "uncertainty": review["uncertainty"],
    }
    if "model" in review:
        recorded["model"] = normalize(review["model"])[:200]
    return recorded, review["verdict"]


def build_claim_map(market, claims, citations=(), today=None, *, trust_reviews=True):
    """Map every claim to an eligible source and a verbatim support fragment."""
    today = today or datetime.now(timezone.utc).date()
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
        key = (ident, quote, normalize(text or ""))
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        review, semantic = _review(claim) if trust_reviews else (None, "unverified")
        mapped.append(
            {
                "claim_id": _claim_id(ident, quote, text),
                "source_id": ident,
                "quote": quote,
                "text": normalize(text) if text else None,
                "support": "exact_excerpt" if quote == excerpt else "excerpt_fragment",
                "semantic_support": semantic,
                "review": review,
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
    today = today or datetime.now(timezone.utc).date()
    mapped = build_claim_map(
        market, claims, citations, today, trust_reviews=execution == "fixture"
    )
    prose_flags = prose_review(text)
    eligible = list(market["citation_ids"])
    contradictions = sorted(market.get("contradictions") or [])
    injection = sorted(
        {
            flag
            for row in market["sources"]
            for flag in row.get("injection_flags", [])
        }
    )
    mapped_claims = mapped["claims"]
    semantic = [item["semantic_support"] for item in mapped_claims]
    # Pattern matches flag drafts for review and can include legitimate budget or target figures.
    missing_claims = not mapped_claims and bool(prose_flags) and (
        bool(eligible) or execution in {"model", "handoff"}
    )
    if contradictions:
        status = "conflict"
    elif missing_claims:
        status = "missing_claims"
    elif not market["sources"]:
        status = "not_applicable"
    elif not eligible:
        status = "no_eligible_sources"
    elif not mapped_claims:
        status = "no_claims"
    elif "rejected" in semantic:
        status = "unsupported_claims"
    elif prose_flags:
        status = "partial"
    elif any(label != "supported" for label in semantic):
        status = "needs_review"
    else:
        status = "verified"

    diagnostics = list(gaps or [])
    if missing_claims:
        diagnostics.append(
            "No structured claim maps the external-fact statements in this output to an eligible source. Check whether the flagged statements are project inputs or proposed targets."
        )
    elif eligible and not mapped_claims:
        diagnostics.append(
            "No structured claim was supplied; treat factual statements as assumptions."
        )
    if contradictions:
        diagnostics.append("Conflicting sources for: " + ", ".join(contradictions))
    if prose_flags:
        diagnostics.append(
            "Unmapped external-fact patterns in prose: " + ", ".join(prose_flags)
        )
    unverified = [
        item["claim_id"]
        for item in mapped_claims
        if item["semantic_support"] in {"unverified", "uncertain"}
    ]
    if unverified:
        diagnostics.append(
            "Verbatim quotes without confirmed semantic support: " + ", ".join(unverified)
        )
    rejected = [
        item["claim_id"] for item in mapped_claims if item["semantic_support"] == "rejected"
    ]
    if rejected:
        diagnostics.append("Claims rejected by semantic review: " + ", ".join(rejected))
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
        "claims": mapped_claims,
        "duplicates_removed": mapped["duplicates_removed"],
        "source_ids": mapped["source_ids"],
        "freshness": mapped["freshness"],
        "injection_flags": injection,
        "contradictions": contradictions,
        "evidence_gaps": diagnostics,
    }



def prose_pattern_names():
    return sorted(PROSE_PATTERNS)
