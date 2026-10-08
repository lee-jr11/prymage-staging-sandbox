"""Locate editable source spans without reserializing the HTML document."""
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import re

FIELDS = {
    "page_title": "title",
    "meta_description": 'meta[name="description"]',
    "hero_headline": ".hero > h1",
    "hero_subhead": ".hero > p",
    "hero_cta_text": "#btn-demo-cta",
}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


def digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


class _Spans(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.lines = [0]
        for match in re.finditer("\n", source):
            self.lines.append(match.end())
        self.stack = []
        self.matches = {field: [] for field in FIELDS}

    def source_offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if len(attributes) != len(attrs):
            raise ValueError("Duplicate HTML attributes")
        start = self.source_offset()
        raw = self.get_starttag_text()
        field = None
        if tag == "title":
            field = "page_title"
        parent = self.stack[-1] if self.stack else None
        if parent and "hero" in parent[1].get("class", "").split():
            if tag == "h1":
                field = "hero_headline"
            elif tag == "p":
                field = "hero_subhead"
        if attributes.get("id") == "btn-demo-cta":
            if tag != "button":
                raise ValueError("CTA must remain a button")
            field = "hero_cta_text"
        if tag == "meta" and attributes.get("name", "").lower() == "description":
            values = list(re.finditer(r'(?<![\w:-])content\s*=\s*([\"\'])(.*?)\1', raw,
                                     re.IGNORECASE | re.DOTALL))
            if len(values) != 1:
                raise ValueError("Description requires one quoted content attribute")
            match = values[0]
            self.matches["meta_description"].append(
                (start + match.start(2), start + match.end(2)))
        if tag not in VOID:
            if self.stack and self.stack[-1][3]:
                raise ValueError("Editable elements must contain plain text only")
            self.stack.append((tag, attributes, start + len(raw), field))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack[-1][0] != tag:
            raise ValueError("Unbalanced HTML")
        _, _, start, field = self.stack.pop()
        if field:
            self.matches[field].append((start, self.source_offset()))

    def handle_comment(self, data):
        if self.stack and self.stack[-1][3]:
            raise ValueError("Comments inside editable fields are not supported")


def spans(source: str) -> dict[str, tuple[int, int]]:
    parser = _Spans(source)
    parser.feed(source)
    parser.close()
    if parser.stack:
        raise ValueError("Unclosed HTML elements")
    for field, matches in parser.matches.items():
        if len(matches) != 1:
            raise ValueError(f"{field}: expected exactly one matching element")
    return {field: matches[0] for field, matches in parser.matches.items()}


def apply_text(source: str, field: str, text: str) -> str:
    if field not in FIELDS:
        raise ValueError("Field is not editable")
    start, end = spans(source)[field]
    return source[:start] + escape(text, quote=True) + source[end:]


def protected_source(source: str, editable: str) -> str:
    """Mask only the selected field: every other source byte remains protected."""
    start, end = spans(source)[editable]
    return source[:start] + "[[EDITABLE_TEXT]]" + source[end:]
