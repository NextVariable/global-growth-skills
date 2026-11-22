"""Read public GitHub repository facts through fixed, bounded HTTPS GETs."""

from datetime import datetime, timedelta, timezone
import json
import re
from ssl import SSLCertVerificationError
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, HTTPRedirectHandler, build_opener

from .contracts import HarnessError, digest

PROVIDER = "github-public"
TOPICS = {"market", "competitor", "icp", "channel"}
REPO = re.compile(r"[A-Za-z0-9_-]{1,39}/[A-Za-z0-9_.-]{1,100}")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _github_json(path):
    request = Request(
        "https://api.github.com" + path,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "gtm-harness"},
        method="GET",
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=15) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise HarnessError("GitHub research response exceeds the byte limit")
            return json.loads(body)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        detail = "rate limited" if status in (403, 429) else f"HTTP {status}"
        raise HarnessError(f"GitHub research unavailable: {detail}") from None
    except URLError as exc:
        if isinstance(exc.reason, SSLCertVerificationError):
            raise HarnessError(
                "GitHub TLS trust failed; configure Python's trusted CA bundle (SSL_CERT_FILE)"
            ) from None
        raise HarnessError("GitHub research unavailable: connection failed") from None
    except (TimeoutError, ValueError, OSError):
        raise HarnessError("GitHub research unavailable: connection or invalid response") from None


def fetch(query, *, get=_github_json, clock=lambda: datetime.now(timezone.utc)):
    if not isinstance(query, dict):
        raise HarnessError("GitHub research requires a query object")
    topic, term, limit = (query.get(k) for k in ("topic", "term", "limit"))
    if (
        topic not in TOPICS
        or not isinstance(term, str)
        or not 1 <= len(term.strip()) <= 120
        or any(ord(c) < 32 or ord(c) == 127 for c in term)
        or type(limit) is not int
        or not 1 <= limit <= 5
    ):
        raise HarnessError("invalid GitHub research topic, query or limit (1–5)")
    repo = query.get("repository")
    if repo is not None:
        if (
            not isinstance(repo, str)
            or not REPO.fullmatch(repo)
            or repo.split("/")[1] in {".", ".."}
        ):
            raise HarnessError("provide a public repository as OWNER/REPO")
        path = "/repos/" + repo
        items = [get(path)]
    else:
        path = "/search/repositories?" + urlencode({"q": term, "per_page": limit})
        payload = get(path)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise HarnessError("GitHub search returned an invalid response")
        if payload.get("incomplete_results") is not False:
            raise HarnessError("GitHub search incomplete; narrow the query or retry")
        items = payload["items"][:limit]
    at = clock().astimezone(timezone.utc)
    return [_record(item, at, topic, path.split("?")[0]) for item in items]


def _record(item, at, topic, endpoint):
    if not isinstance(item, dict):
        raise HarnessError("invalid public repository record")
    repo = item.get("full_name")
    if (
        not isinstance(repo, str)
        or not REPO.fullmatch(repo)
        or repo.split("/")[1] in {".", ".."}
        or item.get("private") is not False
        or item.get("html_url") != "https://github.com/" + repo
    ):
        raise HarnessError("invalid public repository identity")
    counts = {k: item.get(k) for k in ("stargazers_count", "forks_count", "open_issues_count")}
    if any(type(n) is not int or n < 0 for n in counts.values()):
        raise HarnessError("invalid public repository counts")
    ident = "gh-" + digest(repo.casefold())[:20]
    return {
        "id": ident,
        "claim_key": ident,
        "url": item["html_url"],
        "observed_on": at.date().isoformat(),
        "valid_until": (at.date() + timedelta(days=7)).isoformat(),
        "kind": "observation",
        "stance": "supports",
        "excerpt": excerpt({"full_name": repo, **counts}),
        "confidence_basis": "GitHub API snapshot. Counts describe repository activity only.",
        "capture": {
            "provider": PROVIDER,
            "retrieved_at": at.isoformat(),
            "topic": topic,
            "endpoint": endpoint,
            "facts": {"full_name": repo, **counts},
        },
    }


def excerpt(facts):
    repo = facts["full_name"]
    if not REPO.fullmatch(repo) or repo.split("/")[1] in {".", ".."}:
        raise HarnessError("invalid captured repository name")
    return (
        f"GitHub public repository {repo} is listed with {facts['stargazers_count']} stars, "
        f"{facts['forks_count']} forks and {facts['open_issues_count']} open issues or pull requests."
    )
