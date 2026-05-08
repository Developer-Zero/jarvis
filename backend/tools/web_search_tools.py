from html.parser import HTMLParser
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, urlparse
from urllib.request import Request, urlopen

from backend.tools.base import Tool, ToolResult
from backend.tools.browser_tools import read_rendered_page

from config import max_query_length


class _DuckDuckGoParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._active_link = None
        self._active_snippet = False
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        class_name = attrs.get("class", "")
        if tag == "a" and "result__a" in class_name:
            self._active_link = attrs.get("href", "")
            self._text = []
        elif tag == "a" and "result-link" in class_name:
            self._active_link = attrs.get("href", "")
            self._text = []
        elif tag in {"a", "div"} and "result__snippet" in class_name:
            self._active_snippet = True
            self._text = []

    def handle_data(self, data):
        if self._active_link is not None or self._active_snippet:
            text = data.strip()
            if text:
                self._text.append(text)

    def handle_endtag(self, tag):
        if tag == "a" and self._active_link is not None:
            title = " ".join(self._text).strip()
            url = _clean_duckduckgo_url(self._active_link)
            if title and url:
                self.results.append({"title": title, "url": url})
            self._active_link = None
            self._text = []
        elif self._active_snippet and tag in {"a", "div"}:
            snippet = " ".join(self._text).strip()
            if snippet and self.results and "snippet" not in self.results[-1]:
                self.results[-1]["snippet"] = snippet
            self._active_snippet = False
            self._text = []


def _clean_duckduckgo_url(url: str) -> str:
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return target or url
    return url


class _BingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._in_algo = False
        self._active_link = None
        self._active_snippet = False
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        class_name = attrs.get("class", "")
        if tag == "li" and "b_algo" in class_name:
            self._in_algo = True
        elif self._in_algo and tag == "a" and attrs.get("href", "").startswith("http"):
            self._active_link = attrs.get("href", "")
            self._text = []
        elif self._in_algo and tag == "p":
            self._active_snippet = True
            self._text = []

    def handle_data(self, data):
        if self._active_link is not None or self._active_snippet:
            text = data.strip()
            if text:
                self._text.append(text)

    def handle_endtag(self, tag):
        if tag == "a" and self._active_link is not None:
            title = " ".join(self._text).strip()
            if title:
                self.results.append({"title": title, "url": self._active_link})
            self._active_link = None
            self._text = []
        elif tag == "p" and self._active_snippet:
            snippet = " ".join(self._text).strip()
            if snippet and self.results and "snippet" not in self.results[-1]:
                self.results[-1]["snippet"] = snippet
            self._active_snippet = False
            self._text = []
        elif tag == "li" and self._in_algo:
            self._in_algo = False


class _EcosiaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._active_link = None
        self._active_snippet = False
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        class_name = attrs.get("class", "")
        if (
            tag == "a"
            and attrs.get("data-test-id") == "result-link"
            and "result__link" in class_name.split()
        ):
            self._active_link = attrs.get("href", "")
            self._text = []
        elif tag == "p" and attrs.get("data-test-id") == "web-result-description":
            self._active_snippet = True
            self._text = []

    def handle_data(self, data):
        if self._active_link is not None or self._active_snippet:
            text = data.strip()
            if text:
                self._text.append(text)

    def handle_endtag(self, tag):
        if tag == "a" and self._active_link is not None:
            title = " ".join(self._text).strip()
            url = self._active_link
            if title and _is_http_url(url):
                self.results.append({"title": title, "url": url})
            self._active_link = None
            self._text = []
        elif tag == "p" and self._active_snippet:
            snippet = " ".join(self._text).strip()
            if snippet and self.results and "snippet" not in self.results[-1]:
                self.results[-1]["snippet"] = snippet
            self._active_snippet = False
            self._text = []


class _MojeekParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self._active_link = None
        self._active_snippet = False
        self._text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        class_name = attrs.get("class", "")
        if tag == "a" and "title" in class_name.split():
            self._active_link = attrs.get("href", "")
            self._text = []
        elif tag == "p" and "s" in class_name.split():
            self._active_snippet = True
            self._text = []

    def handle_data(self, data):
        if self._active_link is not None or self._active_snippet:
            text = data.strip()
            if text:
                self._text.append(text)

    def handle_endtag(self, tag):
        if tag == "a" and self._active_link is not None:
            title = " ".join(self._text).strip()
            url = self._active_link
            if title and _is_http_url(url):
                self.results.append({"title": title, "url": url})
            self._active_link = None
            self._text = []
        elif tag == "p" and self._active_snippet:
            snippet = " ".join(self._text).strip()
            if snippet and self.results and "snippet" not in self.results[-1]:
                self.results[-1]["snippet"] = snippet
            self._active_snippet = False
            self._text = []


class _ReadablePageParser(HTMLParser):
    SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas"}

    def __init__(self):
        super().__init__()
        self.title = ""
        self.text = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, _attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        text = data.strip()
        if not text:
            return

        if self._in_title:
            self.title = f"{self.title} {text}".strip()
        elif not self._skip_depth:
            self.text.append(text)


def web_search(query: str, max_results: int = 5) -> ToolResult:
    query = query.strip()
    if not query:
        return ToolResult(status="error", error="Query is required")

    max_results = max(1, min(int(max_results), 10))
    errors = []

    for searcher in (
        _search_ecosia,
        _search_mojeek,
        _search_duckduckgo_html,
        _search_duckduckgo_lite,
        _search_bing,
    ):
        try:
            results = searcher(query, max_results)
            if results:
                return ToolResult(status="ok", content=results[:max_results])
            errors.append(f"{searcher.__name__}: no results parsed")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            errors.append(f"{searcher.__name__}: {exc}")

    details = " | ".join(errors) if errors else "all providers returned no results"
    return ToolResult(status="error", error="Search failed: " + details)


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _request_html(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,hu;q=0.8",
        },
    )

    with urlopen(request, timeout=10) as response:
        return response.read().decode("utf-8", errors="ignore")


def _search_duckduckgo_html(query: str, max_results: int) -> list[dict]:
    html = _request_html(f"https://duckduckgo.com/html/?q={quote_plus(query)}")
    parser = _DuckDuckGoParser()
    parser.feed(html)
    return parser.results[:max_results]


def _search_ecosia(query: str, max_results: int) -> list[dict]:
    html = _request_html(f"https://www.ecosia.org/search?q={quote_plus(query)}")
    parser = _EcosiaParser()
    parser.feed(html)
    return parser.results[:max_results]


def _search_mojeek(query: str, max_results: int) -> list[dict]:
    html = _request_html(f"https://www.mojeek.com/search?q={quote_plus(query)}")
    parser = _MojeekParser()
    parser.feed(html)
    return parser.results[:max_results]


def _search_duckduckgo_lite(query: str, max_results: int) -> list[dict]:
    html = _request_html(f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}")
    parser = _DuckDuckGoParser()
    parser.feed(html)
    return parser.results[:max_results]


def _search_bing(query: str, max_results: int) -> list[dict]:
    html = _request_html(f"https://www.bing.com/search?q={quote_plus(query)}")
    parser = _BingParser()
    parser.feed(html)
    return parser.results[:max_results]


def read_web_page(url: str, max_chars: int = 5000, start: int = 0) -> ToolResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ToolResult(status="error", error="Use an absolute http or https URL")

    start = max(0, int(start))
    max_chars = max(500, min(int(max_chars), max(500, max_query_length - 350)))
    rendered = read_rendered_page(url, max_chars, start)
    if rendered.status == "ok":
        content = rendered.content or {}
        text = str(content.get("text") or "")
        if text.strip():
            content["text"] = _clean_text(text)[:max_chars]
            return ToolResult(status="ok", content=content)

    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})

    with urlopen(request, timeout=12) as response:
        content_type = response.headers.get("content-type", "")
        raw = response.read(max_chars * 8)

    if "text/html" not in content_type and "text/plain" not in content_type:
        return ToolResult(status="error", error="Unsupported web content type")

    html = raw.decode("utf-8", errors="ignore")
    if "text/plain" in content_type:
        text = html
        title = parsed.netloc
    else:
        parser = _ReadablePageParser()
        parser.feed(html)
        title = parser.title or parsed.netloc
        text = " ".join(parser.text)

    text = _clean_text(text)
    end = start + max_chars
    return ToolResult(
        status="ok",
        content={
            "title": title,
            "url": url,
            "text": text[start:end],
            "start": start,
            "next_start": end if end < len(text) else None,
            "has_more": end < len(text),
        },
    )


def _clean_text(text: str) -> str:
    lines = []
    for line in text.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if clean:
            lines.append(clean)

    return "\n".join(lines)


WEB_SEARCH_TOOLS = [
    Tool(
        name="web_search",
        description="Search the web and return short results.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["query"],
        },
        function=web_search,
    ),
    Tool(
        name="read_web_page",
        description="Read text from a web page.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 500, "maximum": max_query_length},
                "start": {"type": "integer", "minimum": 0},
            },
            "required": ["url"],
        },
        function=read_web_page,
    ),
]
