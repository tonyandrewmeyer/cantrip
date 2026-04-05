"""Web search tool using DuckDuckGo for open-ended research."""

import html.parser
import re
from dataclasses import dataclass
from typing import Any

import httpx

from cantrip.agent.tools.base import Tool, ToolResult

# DuckDuckGo lite endpoint — simple HTML, no JavaScript, no API key.
_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"

# Ceiling on results to avoid blowing up context.
_MAX_RESULTS_CAP = 10


@dataclass
class _SearchResult:
    """A single search result extracted from DuckDuckGo lite HTML."""

    title: str
    url: str
    snippet: str


class _DDGLiteParser(html.parser.HTMLParser):
    """Extract search results from DuckDuckGo lite HTML.

    The lite page renders results as a sequence of table rows.  Each
    result has a link (``<a class="result-link">``) followed by a
    snippet in a subsequent ``<td>`` with class ``result-snippet``.
    We track state to pair links with their snippets.
    """

    def __init__(self) -> None:
        super().__init__()
        self.results: list[_SearchResult] = []
        self._in_link = False
        self._in_snippet = False
        self._current_url = ""
        self._current_title_parts: list[str] = []
        self._current_snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag == "a" and attr_dict.get("class") == "result-link":
            self._in_link = True
            self._current_url = attr_dict.get("href", "")
            self._current_title_parts = []
        elif tag == "td" and attr_dict.get("class") == "result-snippet":
            self._in_snippet = True
            self._current_snippet_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            self._in_link = False
        elif tag == "td" and self._in_snippet:
            self._in_snippet = False
            title = " ".join(self._current_title_parts).strip()
            snippet = " ".join(self._current_snippet_parts).strip()
            if self._current_url and title:
                self.results.append(
                    _SearchResult(
                        title=title,
                        url=self._current_url,
                        snippet=snippet,
                    )
                )

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._current_title_parts.append(data)
        elif self._in_snippet:
            self._current_snippet_parts.append(data)


def parse_ddg_lite_results(html_text: str, max_results: int = 5) -> list[_SearchResult]:
    """Parse DuckDuckGo lite HTML into structured search results.

    Returns at most *max_results* entries.
    """
    parser = _DDGLiteParser()
    parser.feed(html_text)

    # Deduplicate by URL — DDG lite occasionally repeats results.
    seen: set[str] = set()
    unique: list[_SearchResult] = []
    for result in parser.results:
        if result.url not in seen:
            seen.add(result.url)
            unique.append(result)

    return unique[:max_results]


def _fallback_parse(html_text: str, max_results: int = 5) -> list[_SearchResult]:
    """Regex fallback when the structured parser finds nothing.

    Pulls ``<a>`` tags with ``href`` pointing to external sites and
    nearby text as a rough snippet.
    """
    results: list[_SearchResult] = []
    seen: set[str] = set()
    for match in re.finditer(
        r'<a[^>]+href="(https?://[^"]+)"[^>]*>([^<]+)</a>', html_text
    ):
        url = match.group(1)
        title = match.group(2).strip()
        # Skip DuckDuckGo internal links.
        if "duckduckgo.com" in url or not title:
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append(_SearchResult(title=title, url=url, snippet=""))
        if len(results) >= max_results:
            break
    return results


class WebSearchTool(Tool):
    """Search the web using DuckDuckGo and return structured results."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for information. Returns titles, URLs, and snippets. "
            "Useful for researching operational patterns, deployment guides, and "
            "best practices for workloads."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5, max 10).",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    async def execute(self, query: str, max_results: int = 5) -> ToolResult:
        """Search DuckDuckGo and return structured results."""
        if not query or not query.strip():
            return ToolResult(
                success=False,
                output="",
                error="Search query must not be empty.",
            )

        max_results = min(max(1, max_results), _MAX_RESULTS_CAP)

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "Cantrip/0.1"},
            ) as client:
                response = await client.post(
                    _DDG_LITE_URL,
                    data={"q": query.strip()},
                )
                response.raise_for_status()
        except httpx.TimeoutException:
            return ToolResult(
                success=False,
                output="",
                error=f"Search timed out for query: {query}",
            )
        except httpx.HTTPStatusError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"HTTP {exc.response.status_code} from search engine",
            )
        except httpx.RequestError as exc:
            return ToolResult(
                success=False,
                output="",
                error=f"Connection error during search: {exc}",
            )

        results = parse_ddg_lite_results(response.text, max_results)
        if not results:
            # Try the regex fallback for non-standard HTML layouts.
            results = _fallback_parse(response.text, max_results)

        if not results:
            return ToolResult(
                success=True,
                output="No results found.",
                data={"result_count": 0},
            )

        lines: list[str] = []
        for r in results:
            if r.snippet:
                lines.append(f"- [{r.title}]({r.url}) — {r.snippet}")
            else:
                lines.append(f"- [{r.title}]({r.url})")

        output = "\n".join(lines)
        return ToolResult(
            success=True,
            output=output,
            data={"result_count": len(results)},
        )
