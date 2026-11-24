"""Read-only Hacker News discussion evidence through the public Algolia API.

The provider records public discussion activity only. Points and comments are
not demand, adoption, paying customers or market size, and the linked article
is never fetched.
"""

from datetime import datetime, timedelta, timezone
import json
import re
from ssl import SSLCertVerificationError
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, Request, HTTPRedirectHandler, build_opener

from .contracts import HarnessError, digest

PROVIDER = "hn-public"
TOPICS = {"market", "competitor", "icp", "channel"}
MAX_BYTES = 2_000_000
VALID_DAYS = 7
MAX_EXCERPT = 600
STORY_URL = re.compile(r"^https?://[^\s/?#]+[^\s]*$", re.I)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _hn_json(path):
    request = Request(
        "https://hn.algolia.com" + path,
        headers={"Accept": "application/json", "User-Agent": "gtm-harness"},
        method="GET",
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=15) as response:
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise HarnessError("discussion research response exceeds the byte limit")
            return json.loads(body)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        detail = "rate limited" if status in (403, 429) else f"HTTP {status}"
        raise HarnessError(f"discussion research unavailable: {detail}") from None
    except URLError as exc:
        if isinstance(exc.reason, SSLCertVerificationError):
            raise HarnessError(
                "discussion research TLS trust failed; configure Python's trusted CA bundle "
                "(SSL_CERT_FILE)"
            ) from None
        raise HarnessError("discussion research unavailable: connection failed") from None
    except (TimeoutError, ValueError, OSError):
        raise HarnessError("discussion research unavailable: connection or invalid response") from None


def _text(value, *, limit):
    if not isinstance(value, str):
        raise HarnessError("invalid discussion field")
    value = value.strip()
    if not 1 <= len(value) <= limit or any(ord(char) < 32 for char in value):
        raise HarnessError("invalid discussion field")
    return value


def _story_url(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 2000 or not STORY_URL.fullmatch(value):
        return None
    parts = urlsplit(value)
    if parts.username or parts.password:
        return None
    return value


def _created(value):
    if not isinstance(value, str):
        raise HarnessError("invalid discussion timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HarnessError("invalid discussion timestamp") from None
    if parsed.tzinfo is None:
        raise HarnessError("discussion timestamp is missing a timezone")
    return parsed.astimezone(timezone.utc)


def fetch(query, *, get=_hn_json, clock=lambda: datetime.now(timezone.utc)):
    if not isinstance(query, dict):
        raise HarnessError("discussion research requires a query object")
    topic, term, limit = (query.get(key) for key in ("topic", "term", "limit"))
    if (
        topic not in TOPICS
        or not isinstance(term, str)
        or not 1 <= len(term.strip()) <= 120
        or any(ord(char) < 32 or ord(char) == 127 for char in term)
        or type(limit) is not int
        or not 1 <= limit <= 5
    ):
        raise HarnessError("invalid discussion research topic, query or limit (1–5)")
    path = "/api/v1/search?" + urlencode(
        {"query": term.strip(), "tags": "story", "hitsPerPage": limit}
    )
    payload = get(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("hits"), list):
        raise HarnessError("discussion search returned an invalid response")
    at = clock().astimezone(timezone.utc)
    records = []
    seen = set()
    for item in payload["hits"][:limit]:
        record = _record(item, at, topic, path)
        if record["id"] in seen:
            continue
        seen.add(record["id"])
        records.append(record)
    return records


def _record(item, at, topic, endpoint):
    if not isinstance(item, dict):
        raise HarnessError("invalid public discussion record")
    object_id = item.get("objectID")
    if not isinstance(object_id, str) or not re.fullmatch(r"[0-9]{1,20}", object_id):
        raise HarnessError("invalid public discussion identity")
    title = _text(item.get("title"), limit=300)
    points = item.get("points")
    comments = item.get("num_comments")
    if any(type(value) is not int or value < 0 for value in (points, comments)):
        raise HarnessError("invalid public discussion counts")
    created = _created(item.get("created_at"))
    discussion = f"https://news.ycombinator.com/item?id={object_id}"
    facts = {
        "object_id": object_id,
        "title": title,
        "points": points,
        "num_comments": comments,
        "created_at": created.isoformat(),
        "story_url": _story_url(item.get("url")),
        "discussion_url": discussion,
    }
    ident = "hn-" + digest(object_id)[:20]
    return {
        "id": ident,
        "claim_key": ident,
        "url": discussion,
        "observed_on": at.date().isoformat(),
        "valid_until": (at.date() + timedelta(days=VALID_DAYS)).isoformat(),
        "kind": "observation",
        "stance": "supports",
        "excerpt": excerpt(facts),
        "confidence_basis": (
            "Hacker News search snapshot at retrieval time. Points and comments describe "
            "public discussion activity only; they do not establish demand, adoption, "
            "paying customers or market size."
        ),
        "capture": {
            "provider": PROVIDER,
            "signal": "community_discussion",
            "retrieved_at": at.isoformat(),
            "topic": topic,
            "endpoint": endpoint,
            "facts": facts,
        },
    }


def excerpt(facts):
    title = _text(facts.get("title"), limit=300)
    created = _created(facts.get("created_at")).date().isoformat()
    return (
        f'Hacker News story "{title}", posted {created}, lists {facts["points"]} points and '
        f"{facts['num_comments']} comments in a public snapshot. "
        "Discussion activity is not demand, adoption or market size."
    )[:MAX_EXCERPT]


def verify_capture(row):
    capture = row.get("capture") or {}
    facts = capture.get("facts") or {}
    if capture.get("provider") != PROVIDER:
        raise HarnessError("capture does not use the discussion provider")
    if "signal" in capture and capture["signal"] != "community_discussion":
        raise HarnessError("capture does not declare a discussion signal")
    object_id = str(facts.get("object_id", ""))
    discussion = f"https://news.ycombinator.com/item?id={object_id}"
    expected = "hn-" + digest(object_id)[:20]
    if (
        not re.fullmatch(r"[0-9]{1,20}", object_id)
        or facts.get("discussion_url") != discussion
        or row.get("id") != expected
        or row.get("claim_key") != expected
        or row.get("url") != discussion
        or row.get("excerpt") != excerpt(facts)
        or type(facts.get("points")) is not int
        or facts["points"] < 0
        or type(facts.get("num_comments")) is not int
        or facts["num_comments"] < 0
        or _story_url(facts.get("story_url")) != facts.get("story_url")
    ):
        raise HarnessError("capture does not match the normalized discussion evidence")
