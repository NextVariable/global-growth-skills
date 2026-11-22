"""Read one explicitly supplied public HTTPS page as bounded evidence."""

from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
import ipaddress
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .contracts import HarnessError, digest

PROVIDER = "web-public"
TOPICS = {"market", "competitor", "icp", "channel"}
CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
MAX_BYTES = 1_000_000
MAX_EXCERPT = 1200
DEFAULT_VALID_DAYS = 30
USER_AGENT = "gtm-harness/read-only-public-page"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _VisibleText(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.title = ""
        self.description = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            values = {key.casefold(): value for key, value in attrs}
            name = (values.get("name") or values.get("property") or "").casefold()
            if name in {"description", "og:description"} and not self.description:
                self.description = values.get("content") or ""

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
        else:
            self.parts.append(data)


def _collapse(text):
    return re.sub(r"\s+", " ", text).strip()


def _url(url):
    if not isinstance(url, str) or len(url) > 2000 or any(ord(c) < 32 for c in url):
        raise HarnessError("provide one absolute public HTTPS URL")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.port not in (None, 443)
    ):
        raise HarnessError("web research requires HTTPS on port 443 without credentials")
    host = parts.hostname.casefold().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
        raise HarnessError("web research refuses non-public hostnames")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise HarnessError("web research refuses private or reserved addresses")
    cleaned = urlunsplit(("https", host, parts.path or "/", parts.query, ""))
    return parts, cleaned


def _default_resolve(host):
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise HarnessError("web research could not resolve the public host") from None
    return sorted({info[4][0] for info in infos})


def _check_addresses(host, resolve):
    addresses = resolve(host)
    if not addresses:
        raise HarnessError("web research could not resolve the public host")
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            raise HarnessError("web research received an invalid address") from None
        if not address.is_global:
            raise HarnessError("web research refuses hosts resolving to private or reserved addresses")


def _default_get(url, timeout=10):
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8",
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            body = response.read(MAX_BYTES + 1)
            return response.status, content_type, body
    except HTTPError as exc:
        status = exc.code
        exc.close()
        if 300 <= status < 400:
            raise HarnessError("web research refuses redirects") from None
        raise HarnessError(f"web research unavailable: HTTP {status}") from None
    except URLError:
        raise HarnessError("web research unavailable: connection failed") from None
    except (TimeoutError, OSError):
        raise HarnessError("web research unavailable: timeout or connection error") from None


def _excerpt(visible, description, quote):
    visible = _collapse(visible)
    description = _collapse(description)
    if quote is not None:
        wanted = _collapse(quote)
        if not wanted:
            raise HarnessError("quote must not be blank")
        if wanted not in visible and wanted not in description:
            raise HarnessError("quote is not present in the public page text")
        return wanted[:2000]
    if 40 <= len(description) <= MAX_EXCERPT:
        return description
    if not visible:
        raise HarnessError("public page has no readable text")
    window = visible[:MAX_EXCERPT]
    stop = max(window.rfind(". "), window.rfind("。"))
    return window[: stop + 1] if stop >= 80 else window


def fetch(query, *, get=_default_get, resolve=_default_resolve, clock=lambda: datetime.now(timezone.utc)):
    if not isinstance(query, dict):
        raise HarnessError("web research requires a query object")
    topic = query.get("topic")
    if topic not in TOPICS:
        raise HarnessError("invalid web research topic")
    parts, cleaned = _url(query.get("url"))
    valid_days = query.get("valid_days", DEFAULT_VALID_DAYS)
    if type(valid_days) is not int or not 1 <= valid_days <= 365:
        raise HarnessError("valid_days must be an integer from 1 to 365")
    _check_addresses(parts.hostname.casefold().rstrip("."), resolve)
    status, content_type, body = get(cleaned)
    if status != 200:
        raise HarnessError(f"web research requires HTTP 200, received {status}")
    media = content_type.split(";")[0].strip().casefold()
    if media not in CONTENT_TYPES:
        raise HarnessError("web research requires an HTML or plain-text page")
    if not isinstance(body, bytes) or not body:
        raise HarnessError("web research received an empty response")
    if len(body) > MAX_BYTES:
        raise HarnessError("web research response exceeds the byte limit")
    charset = "utf-8"
    match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    try:
        text = body.decode(charset, errors="replace")
    except LookupError:
        text = body.decode("utf-8", errors="replace")
    parser = _VisibleText()
    if media == "text/plain":
        parser.parts = [text]
    else:
        parser.feed(text)
    excerpt = _excerpt(" ".join(parser.parts), parser.description, query.get("quote"))
    at = clock().astimezone(timezone.utc)
    ident = "web-" + digest(cleaned.casefold())[:20]
    return [
        {
            "id": ident,
            "claim_key": query.get("claim_key") or ident,
            "url": cleaned,
            "observed_on": at.date().isoformat(),
            "valid_until": (at.date() + timedelta(days=valid_days)).isoformat(),
            "kind": "observation",
            "stance": "supports",
            "excerpt": excerpt,
            "confidence_basis": (
                "Unauthenticated public page snapshot at retrieval time. Content may change; "
                "it does not establish demand, adoption or market size."
            ),
            "capture": {
                "provider": PROVIDER,
                "retrieved_at": at.isoformat(),
                "topic": topic,
                "endpoint": urlunsplit((parts.scheme, parts.hostname, parts.path or "/", "", "")),
                "http_status": status,
                "content_type": media,
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "content_bytes": len(body),
                "requested_url": cleaned,
                "title": _collapse(parser.title)[:300],
                "facts": {
                    "url": cleaned,
                    "title": _collapse(parser.title)[:300],
                    "http_status": status,
                    "content_sha256": hashlib.sha256(body).hexdigest(),
                    "visible_characters": len(_collapse(" ".join(parser.parts))),
                },
            },
        }
    ]


def verify_capture(row):
    capture = row.get("capture") or {}
    facts = capture.get("facts") or {}
    expected = "web-" + digest(capture.get("requested_url", "").casefold())[:20]
    if (
        capture.get("provider") != PROVIDER
        or row["id"] != expected
        or row["url"] != capture.get("requested_url")
        or facts.get("url") != row["url"]
        or capture.get("http_status") != 200
        or facts.get("http_status") != 200
        or not re.fullmatch(r"[0-9a-f]{64}", facts.get("content_sha256", ""))
        or facts.get("content_sha256") != capture.get("content_sha256")
        or not row["excerpt"].strip()
    ):
        raise HarnessError("capture does not match the normalized public web evidence")
