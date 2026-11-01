"""HTML to Markdown for knowledge pages: headings, lists and paragraphs kept, page furniture dropped, links collected.

Spec: /architecture/knowledge.md (HTML to Markdown)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

DROPPED = ("nav", "header", "footer", "aside", "form", "script", "style", "noscript", "template")
BLOCKS = ("p", "br", "div", "section", "article", "main", "tr", "table", "ul", "ol", "blockquote", "pre")
MIN_TEXT = 40  # a page with less readable text is skipped


@dataclass
class Page:
    title: str
    markdown: str
    links: list[str] = field(default_factory=list)  # raw href values, every <a> on the page (also inside dropped regions)


class _Converter(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self.title = ""
        self._dropped = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in DROPPED:
            self._dropped += 1
        if tag == "title":
            self._in_title = True
        if self._dropped:
            return
        if tag in ("h1", "h2", "h3"):
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag in ("h4", "h5", "h6"):
            self.parts.append("\n\n**")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in BLOCKS:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in DROPPED and self._dropped:
            self._dropped -= 1
            return
        if tag == "title":
            self._in_title = False
        if self._dropped:
            return
        if tag in ("h4", "h5", "h6"):
            self.parts.append("**\n\n")
        elif tag in ("h1", "h2", "h3", "p", "ul", "ol", "table", "blockquote", "pre"):
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._dropped:
            self.parts.append(re.sub(r"[ \t\r\n]+", " ", data))


def to_markdown(html: str, url: str = "") -> Page:
    """Convert one HTML page. The title is <title>, else the first `#` line, else the URL."""
    conv = _Converter()
    conv.feed(html)
    conv.close()
    lines = [line.strip() for line in "".join(conv.parts).split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    text = re.sub(r"^(#{1,3}) +", r"\1 ", text, flags=re.MULTILINE)
    first_heading = next((m.group(1).strip() for m in re.finditer(r"^#{1,3} (.+)$", text, re.MULTILINE)), "")
    title = " ".join(conv.title.split()) or first_heading or url
    return Page(title=title, markdown=text, links=conv.links)


def readable(page: Page) -> bool:
    """Enough text to be worth indexing (/architecture/knowledge.md: fewer than 40 characters is skipped)."""
    plain = re.sub(r"[#*\-\s]+", " ", page.markdown).strip()
    return len(plain) >= MIN_TEXT
