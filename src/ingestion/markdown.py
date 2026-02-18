"""Lightweight HTML-to-markdown converter using stdlib html.parser.

Used during ingestion to convert RSS article HTML into clean markdown,
reducing token waste when content is later fed to the LLM context.
No third-party dependencies required.
"""

from __future__ import annotations

from html.parser import HTMLParser
import re

# Tags whose entire subtree (content included) is discarded.
_SKIP_TAGS: frozenset[str] = frozenset({
    "script", "style", "head", "nav", "noscript",
    "iframe", "form", "button", "input", "select",
    "option", "textarea", "svg", "canvas",
})

# Block-level tags that force a paragraph break around them.
_BLOCK_TAGS: frozenset[str] = frozenset({
    "p", "div", "section", "article", "main", "header", "footer",
    "address", "blockquote", "table", "tbody", "thead", "tfoot",
    "tr", "td", "th", "dl", "dt", "dd", "figure", "figcaption", "aside",
})


class _HTMLToMarkdownParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth: int = 0
        self._list_stack: list[str] = []    # "ul" or "ol"
        self._list_counters: list[int] = []

    # ------------------------------------------------------------------
    # HTMLParser callbacks
    # ------------------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._skip_depth:
            self._skip_depth += 1
            return
        if tag in _SKIP_TAGS:
            self._skip_depth = 1
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._block()
            self._parts.append("#" * int(tag[1]) + " ")
        elif tag == "br":
            self._parts.append("\n")
        elif tag in _BLOCK_TAGS:
            self._block()
        elif tag in ("ul", "ol"):
            self._list_stack.append(tag)
            self._list_counters.append(0)
        elif tag == "li":
            self._block()
            indent = "  " * (len(self._list_stack) - 1)
            if self._list_stack and self._list_stack[-1] == "ol":
                self._list_counters[-1] += 1
                self._parts.append(f"{indent}{self._list_counters[-1]}. ")
            else:
                self._parts.append(f"{indent}- ")
        elif tag in ("strong", "b"):
            self._parts.append("**")
        elif tag in ("em", "i"):
            self._parts.append("*")
        elif tag == "code":
            self._parts.append("`")
        elif tag == "pre":
            self._block()
            self._parts.append("```\n")
        elif tag == "hr":
            self._block()
            self._parts.append("---")
            self._block()

    def handle_endtag(self, tag: str) -> None:
        if self._skip_depth:
            self._skip_depth -= 1
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._block()
        elif tag in _BLOCK_TAGS:
            self._block()
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
                self._list_counters.pop()
        elif tag == "li":
            self._block()
        elif tag in ("strong", "b"):
            self._parts.append("**")
        elif tag in ("em", "i"):
            self._parts.append("*")
        elif tag == "code":
            self._parts.append("`")
        elif tag == "pre":
            self._parts.append("\n```")
            self._block()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        # Collapse runs of spaces/tabs (preserve intentional newlines in <pre>).
        normalized = re.sub(r"[ \t]+", " ", data)
        if normalized.strip():
            self._parts.append(normalized)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _block(self) -> None:
        """Ensure a blank-line separator before the next content block."""
        joined = "".join(self._parts)
        if joined.endswith("\n\n"):
            return
        if joined.endswith("\n"):
            self._parts.append("\n")
        elif joined:
            self._parts.append("\n\n")

    def result(self) -> str:
        text = "".join(self._parts)
        # Collapse runs of 3+ newlines to a single blank line.
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Strip trailing whitespace from each line.
        lines = [line.rstrip() for line in text.splitlines()]
        return "\n".join(lines).strip()


def html_to_markdown(html: str) -> str:
    """Convert an HTML string to clean markdown text.

    Strips boilerplate tags (script, style, nav, etc.), converts structural
    elements (headings, lists, emphasis) to markdown equivalents, decodes
    HTML entities, and normalises whitespace.

    Plain-text content (no ``<`` character) passes through unchanged at zero
    parsing cost, so this is safe to call on YouTube transcripts too.
    """
    if "<" not in html:
        return html.strip()

    parser = _HTMLToMarkdownParser()
    parser.feed(html)
    return parser.result()
