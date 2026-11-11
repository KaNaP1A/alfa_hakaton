"""Access-aware extraction of source HTML into searchable text and passages."""

from collections import defaultdict
from html.parser import HTMLParser


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "iframe", "svg", "noscript"}:
            self.hidden += 1
        if tag in {"p", "div", "li", "br", "h1", "h2", "h3", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "iframe", "svg", "noscript"} and self.hidden:
            self.hidden -= 1
        self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_text(value):
    parser = TextExtractor()
    parser.feed(value or "")
    parser.close()
    return " ".join("".join(parser.parts).split())


def enrich_content(catalog, article_blocks, lesson_blocks):
    def collect(blocks, key):
        grouped = defaultdict(list)
        for block in blocks:
            text = html_text(block.get("HtmlContent"))
            if text:
                try:
                    order = int(block.get("Order") or 0)
                except ValueError:
                    order = 0
                grouped[block[key]].append((order, block["Id"], text))
        return {
            key: " ".join(text for _, _, text in sorted(values)) for key, values in grouped.items()
        }

    articles = collect(article_blocks, "ArticleId")
    lessons = collect(lesson_blocks, "LessonId")
    counts = {"article_bodies": 0, "lesson_bodies": 0, "body_characters": 0}
    for item in catalog:
        item["body"] = ""
        if (
            item["kind"] == "article"
            and item["access_type"] == "open"
            and item["content_public_flag"] == "t"
        ):
            item["body"] = articles.get(item["source_id"], "")
            counts["article_bodies"] += bool(item["body"])
        for lesson in item.get("lessons", []):
            # The eligibility of the lesson and all its parents was checked first.
            lesson["body"] = lessons.get(lesson["lesson_id"], "")
            counts["lesson_bodies"] += bool(lesson["body"])
        counts["body_characters"] += len(item["body"])
        counts["body_characters"] += sum(len(row["body"]) for row in item.get("lessons", []))
        # Autocomplete stays metadata-only; unrestricted bodies are not phrase suggestions.
        item["provenance"]["body"] = "ArticleEmbedItems.HtmlContent" if item["body"] else None
    return counts


def make_units(catalog, tokenizer, window=96, overlap=16):
    """Bound passages by actual model tokens, preserving source and parent IDs."""
    if not 0 <= overlap < window:
        raise ValueError("overlap must be smaller than token window")
    units = []
    for item in catalog:
        sources = [
            (
                "card",
                None,
                " ".join(
                    [
                        item["title"],
                        item["description"],
                        *item["topics"],
                        *item["tags"],
                        *item["industries"],
                    ]
                ),
            )
        ]
        if item.get("body"):
            sources.append(("body", None, item["title"] + ". " + item["body"]))
        for lesson in item.get("lessons", []):
            sources.append(
                (
                    "lesson",
                    lesson["lesson_id"],
                    " ".join([lesson["title"], lesson["description"], lesson.get("body", "")]),
                )
            )
        for source, lesson_id, text in sources:
            encoded = tokenizer.encode(text, add_special_tokens=False, truncation=False)
            for start in range(0, len(encoded), window - overlap):
                units.append(
                    {
                        "entity_key": item["entity_key"],
                        "source": source,
                        "lesson_id": lesson_id,
                        "token_start": start,
                        "text": tokenizer.decode(
                            encoded[start : start + window], skip_special_tokens=True
                        ),
                    }
                )
                if start + window >= len(encoded):
                    break
    return units
