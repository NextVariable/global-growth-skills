"""One registry for every read-only research provider.

A provider turns a bounded query into normalized evidence records and can
re-verify a stored capture without network access. Adding a provider must not
widen write permissions or bypass the capture checks in ``research.review``.
"""

from .contracts import HarnessError
from . import github_research, hn_research, web_research

MODULES = {
    github_research.PROVIDER: github_research,
    web_research.PROVIDER: web_research,
    hn_research.PROVIDER: hn_research,
}
FIXTURE_SAFE = {
    github_research.PROVIDER: "public repository activity only",
    web_research.PROVIDER: "one explicit public HTTPS page",
    hn_research.PROVIDER: "public Hacker News discussion activity only",
}


def names():
    return sorted(MODULES)


def module(provider):
    found = MODULES.get(provider)
    if found is None:
        raise HarnessError("unknown research provider")
    return found


def fetch(provider, query, **kwargs):
    return module(provider).fetch(query, **kwargs)


def verify_capture(row):
    if not isinstance(row, dict):
        raise HarnessError("capture row must be an object")
    capture = row.get("capture")
    if not isinstance(capture, dict):
        raise HarnessError("source capture is missing")
    module(capture.get("provider")).verify_capture(row)
