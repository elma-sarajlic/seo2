from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SEO_DIR = ROOT / "seo"
BLOG_DIR = ROOT / "blog"
CONFIG_PATH = SEO_DIR / "config.json"
KEYWORDS_PATH = ROOT / "keywords.json"
IMAGES_PATH = SEO_DIR / "image-library.json"
STATE_PATH = SEO_DIR / "state.json"
TEMPLATE_PATH = SEO_DIR / "article-template.html"
BLOG_INDEX_PATH = ROOT / "blog.html"
SITEMAP_PATH = ROOT / "sitemap.xml"
FEED_PATH = BLOG_DIR / "feed.json"
DRAFT_PAYLOAD_PATH = SEO_DIR / "draft-payload.json"

BLOG_START = "<!-- SEO-ARTICLES:START -->"
BLOG_END = "<!-- SEO-ARTICLES:END -->"
SITEMAP_START = "<!-- SEO-URLS:START -->"
SITEMAP_END = "<!-- SEO-URLS:END -->"

ALLOWED_TAGS = {
    "p", "h2", "h3", "ul", "ol", "li", "strong", "em", "a", "blockquote",
    "div", "table", "thead", "tbody", "tr", "th", "td", "br",
}
VOID_TAGS = {"br"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-{2,}", "-", value).strip("-")[:80]


def plain_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def word_count(html: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", plain_text(html)))


def require_markers(text: str, start: str, end: str, path: Path) -> None:
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
        raise RuntimeError(f"{path.name} must contain exactly one ordered {start} / {end} marker pair")


def replace_marker_block(text: str, start: str, end: str, content: str) -> str:
    before, remainder = text.split(start, 1)
    _, after = remainder.split(end, 1)
    return f"{before}{start}\n{content.rstrip()}\n{end}{after}"


@dataclass(frozen=True)
class KeywordChoice:
    keyword: str
    cluster: str
    searches: int
    competition: str
    competition_index: int
    angle: str


def keyword_score(item: dict[str, Any]) -> float:
    searches = max(0, int(item.get("avg_monthly_searches") or 0))
    competition_index = max(0, int(item.get("competition_index") or 0))
    specificity = min(5, len(str(item.get("keyword") or "").split()))
    return math.log10(searches + 1) + specificity * 0.16 - competition_index * 0.012


def choose_keyword(
    keyword_data: dict[str, Any],
    config: dict[str, Any],
    state: dict[str, Any],
    requested_keyword: str = "",
) -> KeywordChoice:
    clusters = keyword_data.get("primary_clusters") or {}
    excluded = {str(item).casefold() for item in config.get("excluded_keywords", [])}
    usage: dict[str, int] = {}
    for item in state.get("generated", []):
        if isinstance(item, dict):
            key = str(item.get("keyword") or "").casefold()
            usage[key] = usage.get(key, 0) + 1
    angles = [str(item) for item in config.get("content_angles", []) if str(item).strip()]
    if not angles:
        angles = ["practical guide"]

    all_items: list[tuple[str, dict[str, Any]]] = []
    for cluster, items in clusters.items():
        for item in items:
            all_items.append((cluster, item))

    if requested_keyword.strip():
        requested = requested_keyword.strip()
        match = next(
            ((cluster, item) for cluster, item in all_items if str(item.get("keyword", "")).casefold() == requested.casefold()),
            None,
        )
        if match:
            cluster, item = match
        else:
            cluster, item = "manual_topic", {
                "keyword": requested,
                "avg_monthly_searches": 0,
                "competition": "Unknown",
                "competition_index": 0,
            }
        return KeywordChoice(
            requested,
            cluster,
            int(item.get("avg_monthly_searches") or 0),
            str(item.get("competition") or "Unknown"),
            int(item.get("competition_index") or 0),
            "owner-specified topic",
        )

    cluster_order = [name for name in config.get("cluster_order", []) if name in clusters]
    if not cluster_order:
        cluster_order = list(clusters)
    last_cluster = str(state.get("last_cluster") or "")
    start_index = (cluster_order.index(last_cluster) + 1) % len(cluster_order) if last_cluster in cluster_order else 0

    for offset in range(len(cluster_order)):
        cluster = cluster_order[(start_index + offset) % len(cluster_order)]
        available = [
            item for item in clusters.get(cluster, [])
            if str(item.get("keyword") or "").casefold() not in excluded
            and usage.get(str(item.get("keyword") or "").casefold(), 0) < len(angles)
        ]
        if available:
            item = max(
                available,
                key=lambda candidate: (
                    -usage.get(str(candidate.get("keyword") or "").casefold(), 0),
                    keyword_score(candidate),
                ),
            )
            count = usage.get(str(item.get("keyword") or "").casefold(), 0)
            return KeywordChoice(
                str(item["keyword"]),
                cluster,
                int(item.get("avg_monthly_searches") or 0),
                str(item.get("competition") or "Unknown"),
                int(item.get("competition_index") or 0),
                angles[count],
            )

    raise RuntimeError("All configured keyword and content-angle combinations have already been used")


def choose_image(images: list[dict[str, Any]], choice: KeywordChoice) -> dict[str, Any]:
    matching = [image for image in images if choice.cluster in image.get("clusters", [])]
    pool = matching or images
    if not pool:
        raise RuntimeError("seo/image-library.json must contain at least one image")
    seed = int(hashlib.sha256(choice.keyword.encode("utf-8")).hexdigest()[:12], 16)
    image = dict(pool[seed % len(pool)])
    local_path = ROOT / str(image.get("path") or "")
    if not local_path.is_file():
        raise RuntimeError(f"Configured article image does not exist: {local_path.relative_to(ROOT)}")
    return image


def article_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "slug": {"type": "string"},
            "meta_description": {"type": "string"},
            "excerpt": {"type": "string"},
            "category": {"type": "string"},
            "lead": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "image_alt": {"type": "string"},
            "html": {"type": "string"},
            "faq": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "answer": {"type": "string"},
                    },
                    "required": ["question", "answer"],
                },
            },
        },
        "required": [
            "title", "slug", "meta_description", "excerpt", "category", "lead",
            "tags", "image_alt", "html", "faq",
        ],
    }


def build_prompt(choice: KeywordChoice, image: dict[str, Any], config: dict[str, Any]) -> str:
    category = config.get("category_labels", {}).get(choice.cluster, "Product documentation")
    facts = "\n".join(f"- {fact}" for fact in config.get("brand_facts", []))
    internal_links = "\n".join(f"- {link}" for link in config.get("allowed_internal_links", []))
    return f"""
Write an original, publication-ready SEO article for assemblymaker.com.

Primary keyword: {choice.keyword}
Keyword cluster: {choice.cluster}
Content angle: {choice.angle}
Editorial category: {category}
Approximate search data supplied by the owner: {choice.searches} monthly searches, {choice.competition} competition (index {choice.competition_index}).
Audience: hardware creators, manufacturing teams, SaaS builders, and product-documentation specialists.
Target length: about {int(config.get('article_word_count', 1200))} words.
Existing site image that will accompany the article: {image.get('path')} ({image.get('alt')}).

Verified Assembly Maker facts:
{facts}

Allowed internal link targets:
{internal_links}

Editorial requirements:
- Answer the keyword's real search intent. Do not merely repeat the keyword.
- Start with a 2-4 sentence direct answer in the lead field.
- Write for a knowledgeable human reader. Avoid filler, hype, fake quotations, and claims about SEO results.
- Use the exact primary keyword naturally in the title or first 100 words, one heading where useful, and sparingly elsewhere.
- Provide specific steps, decision criteria, failure modes, review checks, or examples.
- Include a compact key-takeaways list and at least four useful h2 sections.
- Use h3 only when it improves the hierarchy. Do not include an h1 in html.
- Add exactly one restrained callout using <div class="article-callout">.</div>.
- Link naturally to 2-3 distinct allowed internal pages using root-relative URLs. Include one final, restrained CTA to /manual.html.
- Do not add external links or cite studies unless a source was supplied here.
- Do not invent specifications, prices, customer results, integrations, certifications, or features.
- The html field may use only p, h2, h3, ul, ol, li, strong, em, a, blockquote, div, table, thead, tbody, tr, th, td, and br.
- Supply three concise FAQ items that are answered by the article.
- Keep the meta description between 145 and 160 characters and the excerpt below 220 characters.
- The image_alt field must truthfully describe the supplied existing site image in the article's context.
- Return valid JSON only, matching the requested schema.
""".strip()


def generate_with_gemini(choice: KeywordChoice, image: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required unless --fixture is used")
    model = os.getenv("GEMINI_TEXT_MODEL", "gemini-2.5-flash").strip()
    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=build_prompt(choice, image, config),
        config={
            "system_instruction": (
                "You are Assembly Maker's careful technical editor. Prioritize accuracy, usefulness, "
                "natural search language, clean HTML, and claims supported by the supplied product facts."
            ),
            "temperature": 0.65,
            "response_mime_type": "application/json",
            "response_schema": article_schema(),
        },
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty article")
    return json.loads(response.text)


class ArticleSanitizer(HTMLParser):
    def __init__(self, allowed_internal_links: set[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.allowed_internal_links = allowed_internal_links
        self.parts: list[str] = []
        self.stack: list[str] = []

    def _safe_href(self, value: str) -> str:
        href = value.strip()
        parsed = urlparse(href)
        if parsed.scheme or parsed.netloc:
            if parsed.scheme == "https" and parsed.netloc.lower() in {"assemblymaker.com", "www.assemblymaker.com"}:
                href = parsed.path or "/"
                if parsed.query:
                    href += "?" + parsed.query
            else:
                return ""
        if not href.startswith("/"):
            href = "/" + href.lstrip("./")
        path = href.split("?", 1)[0].split("#", 1)[0]
        return href if path in self.allowed_internal_links else ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in ALLOWED_TAGS:
            return
        rendered_attrs = ""
        if tag == "a":
            href = self._safe_href(next((value or "" for name, value in attrs if name.lower() == "href"), ""))
            if not href:
                return
            rendered_attrs = f' href="{escape(href, quote=True)}"'
        elif tag == "div":
            class_name = next((value or "" for name, value in attrs if name.lower() == "class"), "")
            if class_name != "article-callout":
                return
            rendered_attrs = ' class="article-callout"'
        self.parts.append(f"<{tag}{rendered_attrs}>")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag not in ALLOWED_TAGS or tag in VOID_TAGS or tag not in self.stack:
            return
        while self.stack:
            open_tag = self.stack.pop()
            self.parts.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        self.parts.append(escape(data, quote=False))

    def close(self) -> None:
        super().close()
        while self.stack:
            self.parts.append(f"</{self.stack.pop()}>")

    def result(self) -> str:
        return "".join(self.parts).strip()


def sanitize_html(html: str, allowed_internal_links: set[str]) -> str:
    sanitizer = ArticleSanitizer(allowed_internal_links)
    sanitizer.feed(html)
    sanitizer.close()
    return sanitizer.result()


def clean_article(
    article: dict[str, Any],
    choice: KeywordChoice,
    image: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    required = {"title", "meta_description", "excerpt", "lead", "html", "faq"}
    missing = sorted(name for name in required if not str(article.get(name) or "").strip())
    if missing:
        raise RuntimeError("Article is missing required values: " + ", ".join(missing))

    cleaned = dict(article)
    cleaned["title"] = plain_text(str(article["title"]))
    cleaned["slug"] = slugify(str(article.get("slug") or cleaned["title"]))
    cleaned["meta_description"] = plain_text(str(article["meta_description"]))
    cleaned["excerpt"] = plain_text(str(article["excerpt"]))
    cleaned["lead"] = plain_text(str(article["lead"]))
    cleaned["category"] = plain_text(str(article.get("category") or "")) or config.get("category_labels", {}).get(choice.cluster, "Product documentation")
    cleaned["tags"] = [plain_text(str(tag)) for tag in article.get("tags", []) if plain_text(str(tag))][:5]
    cleaned["image_alt"] = plain_text(str(image.get("alt") or article.get("image_alt") or "Assembly Maker example"))
    cleaned["html"] = sanitize_html(
        str(article["html"]),
        set(config.get("allowed_internal_links", [])),
    )
    cleaned["faq"] = [
        {
            "question": plain_text(str(item.get("question") or "")),
            "answer": plain_text(str(item.get("answer") or "")),
        }
        for item in article.get("faq", [])
        if isinstance(item, dict) and item.get("question") and item.get("answer")
    ][:5]
    cleaned["primary_keyword"] = choice.keyword
    cleaned["keyword_cluster"] = choice.cluster
    cleaned["content_angle"] = choice.angle
    cleaned["image_path"] = str(image["path"]).replace("\\", "/")

    if not cleaned["slug"]:
        raise RuntimeError("Article title did not produce a usable slug")
    if not (25 <= len(cleaned["title"]) <= 80):
        raise RuntimeError(f"Article title must be 25-80 characters; received {len(cleaned['title'])}")
    if not (100 <= len(cleaned["meta_description"]) <= 170):
        raise RuntimeError(f"Meta description must be 100-170 characters; received {len(cleaned['meta_description'])}")
    if len(cleaned["excerpt"]) > 260:
        raise RuntimeError("Article excerpt must be 260 characters or fewer")
    if len(cleaned["faq"]) < 3:
        raise RuntimeError("Article must contain at least three valid FAQ items")
    minimum_words = int(config.get("minimum_word_count", 750))
    actual_words = word_count(cleaned["lead"] + " " + cleaned["html"])
    if actual_words < minimum_words:
        raise RuntimeError(f"Article is too short: {actual_words} words; minimum is {minimum_words}")
    if cleaned["html"].lower().count("<h2>") < 4:
        raise RuntimeError("Article must contain at least four h2 sections")
    if cleaned["html"].count('class="article-callout"') != 1:
        raise RuntimeError("Article must contain exactly one article-callout")
    if choice.keyword.casefold() not in (cleaned["title"] + " " + cleaned["lead"] + " " + plain_text(cleaned["html"])[:600]).casefold():
        raise RuntimeError(f"Primary keyword is missing from the title or opening copy: {choice.keyword}")
    return cleaned


def faq_html(items: list[dict[str, str]]) -> str:
    details = []
    for item in items:
        details.append(
            '<details class="article-faq-item">'
            f'<summary>{escape(item["question"])}</summary>'
            f'<p>{escape(item["answer"])}</p>'
            '</details>'
        )
    return '<section class="article-faq"><h2>Frequently asked questions</h2>' + "".join(details) + "</section>"


def structured_data(article: dict[str, Any], published: date, canonical: str, image_url: str, config: dict[str, Any]) -> str:
    data = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "BlogPosting",
                "headline": article["title"],
                "description": article["meta_description"],
                "image": image_url,
                "datePublished": published.isoformat(),
                "dateModified": published.isoformat(),
                "mainEntityOfPage": canonical,
                "author": {"@type": "Organization", "name": config.get("author_name", "Assembly Maker")},
                "publisher": {
                    "@type": "Organization",
                    "name": config.get("site_name", "Assembly Maker"),
                    "logo": {"@type": "ImageObject", "url": config["site_url"].rstrip("/") + "/assembly-maker-logo.png"},
                },
                "keywords": article["tags"],
                "articleSection": article["category"],
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Home", "item": config["site_url"].rstrip("/") + "/"},
                    {"@type": "ListItem", "position": 2, "name": "Blog", "item": config["site_url"].rstrip("/") + "/blog.html"},
                    {"@type": "ListItem", "position": 3, "name": article["title"], "item": canonical},
                ],
            },
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {
                        "@type": "Question",
                        "name": item["question"],
                        "acceptedAnswer": {"@type": "Answer", "text": item["answer"]},
                    }
                    for item in article["faq"]
                ],
            },
        ],
    }
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_article(article: dict[str, Any], published: date, config: dict[str, Any]) -> str:
    site_url = config["site_url"].rstrip("/")
    canonical = f"{site_url}/blog/{article['slug']}.html"
    image_url = f"{site_url}/{article['image_path'].lstrip('/')}"
    display_date = published.strftime("%B %d, %Y").replace(" 0", " ")
    tags = "".join(f'<span>{escape(tag)}</span>' for tag in article["tags"])
    replacements = {
        "SEO_TITLE": escape(f"{article['title']} | Assembly Maker"),
        "TITLE": escape(article["title"]),
        "META_DESCRIPTION": escape(article["meta_description"], quote=True),
        "CANONICAL_URL": escape(canonical, quote=True),
        "IMAGE_URL": escape(image_url, quote=True),
        "IMAGE_PATH": escape("/" + article["image_path"].lstrip("/"), quote=True),
        "IMAGE_ALT": escape(article["image_alt"], quote=True),
        "PUBLISHED_ISO": published.isoformat(),
        "PUBLISHED_DATE": published.isoformat(),
        "DISPLAY_DATE": display_date,
        "CATEGORY": escape(article["category"]),
        "LEAD": escape(article["lead"]),
        "TAGS": tags,
        "ARTICLE_HTML": article["html"],
        "FAQ_HTML": faq_html(article["faq"]),
        "STRUCTURED_DATA": structured_data(article, published, canonical, image_url, config),
        "YEAR": str(published.year),
    }
    rendered = TEMPLATE_PATH.read_text(encoding="utf-8")
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    remaining = re.findall(r"\{\{[A-Z_]+\}\}", rendered)
    if remaining:
        raise RuntimeError("Unfilled article template values: " + ", ".join(sorted(set(remaining))))
    return rendered


def load_feed() -> list[dict[str, Any]]:
    if not FEED_PATH.exists():
        return []
    value = read_json(FEED_PATH)
    if not isinstance(value, list):
        raise RuntimeError("blog/feed.json must contain a JSON array")
    return value


def card_html(item: dict[str, Any]) -> str:
    return (
        '            <article class="card blog-card">'
        f'<p class="blog-meta"><time datetime="{escape(item["published"])}">{escape(item["display_date"])}</time> · {escape(item["category"])}</p>'
        f'<h2><a href="{escape(item["path"], quote=True)}">{escape(item["title"])}</a></h2>'
        f'<p>{escape(item["excerpt"])}</p>'
        f'<a class="text-link" href="{escape(item["path"], quote=True)}">Read more <span aria-hidden="true">→</span></a>'
        '</article>'
    )


def update_blog_index(feed: list[dict[str, Any]]) -> None:
    text = BLOG_INDEX_PATH.read_text(encoding="utf-8")
    require_markers(text, BLOG_START, BLOG_END, BLOG_INDEX_PATH)
    generated_cards = "\n".join(card_html(item) for item in feed)
    write_text(BLOG_INDEX_PATH, replace_marker_block(text, BLOG_START, BLOG_END, generated_cards))


def sitemap_entry(item: dict[str, Any], site_url: str) -> str:
    return (
        "  <url>\n"
        f"    <loc>{escape(site_url.rstrip('/') + '/' + item['path'])}</loc>\n"
        f"    <lastmod>{escape(item['published'])}</lastmod>\n"
        "    <changefreq>monthly</changefreq>\n"
        "    <priority>0.7</priority>\n"
        "  </url>"
    )


def update_sitemap(feed: list[dict[str, Any]], config: dict[str, Any], published: date) -> None:
    text = SITEMAP_PATH.read_text(encoding="utf-8")
    require_markers(text, SITEMAP_START, SITEMAP_END, SITEMAP_PATH)
    text = re.sub(
        r"(<loc>https://assemblymaker\.com/blog\.html</loc>\s*<lastmod>)[^<]+",
        rf"\g<1>{published.isoformat()}",
        text,
        count=1,
    )
    entries = "\n".join(sitemap_entry(item, config["site_url"]) for item in feed)
    write_text(SITEMAP_PATH, replace_marker_block(text, SITEMAP_START, SITEMAP_END, entries))


def publish_article(
    article: dict[str, Any],
    choice: KeywordChoice,
    config: dict[str, Any],
    state: dict[str, Any],
    published: date,
) -> dict[str, Any]:
    feed = load_feed()
    base_slug = article["slug"]
    candidate_slug = base_slug
    suffix = slugify(choice.angle) or "article"
    sequence = 2
    while True:
        existing = next((item for item in feed if item.get("slug") == candidate_slug), None)
        if not existing:
            break
        same_topic = (
            str(existing.get("primary_keyword") or "").casefold() == choice.keyword.casefold()
            and str(existing.get("content_angle") or "").casefold() == choice.angle.casefold()
        )
        if same_topic:
            break
        candidate_slug = f"{base_slug}-{suffix}" if sequence == 2 else f"{base_slug}-{suffix}-{sequence}"
        sequence += 1
    article["slug"] = candidate_slug[:110].rstrip("-")
    article_path = BLOG_DIR / f"{article['slug']}.html"
    existing = next((item for item in feed if item.get("slug") == article["slug"]), None)
    if article_path.exists() and not existing:
        raise RuntimeError(f"Refusing to overwrite an untracked article: {article_path.relative_to(ROOT)}")

    rendered = render_article(article, published, config)
    write_text(article_path, rendered)
    display_date = published.strftime("%B %d, %Y").replace(" 0", " ")
    feed_item = {
        "slug": article["slug"],
        "path": f"blog/{article['slug']}.html",
        "title": article["title"],
        "excerpt": article["excerpt"],
        "category": article["category"],
        "published": published.isoformat(),
        "display_date": display_date,
        "primary_keyword": choice.keyword,
        "keyword_cluster": choice.cluster,
        "content_angle": choice.angle,
        "image_path": article["image_path"],
    }
    feed = [item for item in feed if item.get("slug") != article["slug"]]
    feed.insert(0, feed_item)
    feed.sort(key=lambda item: (str(item.get("published", "")), str(item.get("slug", ""))), reverse=True)
    write_json(FEED_PATH, feed)
    update_blog_index(feed)
    update_sitemap(feed, config, published)

    generated = [
        item for item in state.get("generated", [])
        if str(item.get("slug") or "") != article["slug"]
    ]
    generated.append({
        "keyword": choice.keyword,
        "cluster": choice.cluster,
        "angle": choice.angle,
        "slug": article["slug"],
        "published": published.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    state["last_cluster"] = choice.cluster
    state["generated"] = generated
    write_json(STATE_PATH, state)
    draft_id = int(hashlib.sha256(article["slug"].encode("utf-8")).hexdigest()[:12], 16)
    write_json(DRAFT_PAYLOAD_PATH, {
        "id": draft_id,
        "source": "assemblymaker",
        "status": "draft",
        "title": article["title"],
        "excerpt": article["excerpt"],
        "content_html": article["html"] + "\n" + faq_html(article["faq"]),
        "article_html": rendered,
        "article_path": str(article_path.relative_to(ROOT)).replace("\\", "/"),
        "feed_item": feed_item,
        "original_image_path": article["image_path"],
        "featured_image": "",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return feed_item


def restore_draft_payload(published: date, state: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the review payload when a same-day workflow run is retried."""
    feed_item = next(
        (
            item
            for item in load_feed()
            if str(item.get("published") or "") == published.isoformat()
        ),
        None,
    )
    if not isinstance(feed_item, dict):
        raise RuntimeError("Today's generated article is missing from blog/feed.json")
    article_path = ROOT / str(feed_item["path"])
    if not article_path.is_file():
        raise RuntimeError(f"Today's generated article is missing: {article_path.relative_to(ROOT)}")
    rendered = article_path.read_text(encoding="utf-8")
    content_match = re.search(r"</figure>\s*(.*?)\s*</article>", rendered, flags=re.DOTALL)
    if not content_match:
        raise RuntimeError("Could not recover the article content for review")
    matching_state = next(
        (
            item
            for item in state.get("generated", [])
            if isinstance(item, dict) and item.get("slug") == feed_item.get("slug")
        ),
        {},
    )
    payload = {
        "id": int(hashlib.sha256(str(feed_item["slug"]).encode("utf-8")).hexdigest()[:12], 16),
        "source": "assemblymaker",
        "status": "draft",
        "title": str(feed_item["title"]),
        "excerpt": str(feed_item.get("excerpt") or ""),
        "content_html": content_match.group(1).strip(),
        "article_html": rendered,
        "article_path": str(feed_item["path"]),
        "feed_item": feed_item,
        "original_image_path": str(feed_item.get("image_path") or ""),
        "featured_image": "",
        "created_at": str(matching_state.get("generated_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")),
    }
    write_json(DRAFT_PAYLOAD_PATH, payload)
    return payload


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate and publish an Assembly Maker static SEO article")
    parser.add_argument("--keyword", default=os.getenv("ARTICLE_KEYWORD", ""), help="Optional one-off keyword or topic")
    parser.add_argument("--fixture", type=Path, help="Use article JSON from a local fixture instead of calling Gemini")
    parser.add_argument("--date", dest="published_date", help="Publication date in YYYY-MM-DD format")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = read_json(CONFIG_PATH)
    keyword_data = read_json(KEYWORDS_PATH)
    images = read_json(IMAGES_PATH)
    state = read_json(STATE_PATH)
    published = date.fromisoformat(args.published_date) if args.published_date else date.today()
    if not args.keyword.strip() and any(
        str(item.get("published") or "") == published.isoformat()
        for item in state.get("generated", [])
        if isinstance(item, dict)
    ):
        restore_draft_payload(published, state)
        print(json.dumps({"status": "already-generated", "date": published.isoformat()}))
        return 0
    choice = choose_keyword(keyword_data, config, state, args.keyword)
    image = choose_image(images, choice)
    article_data = read_json(args.fixture.resolve()) if args.fixture else generate_with_gemini(choice, image, config)
    article = clean_article(article_data, choice, image, config)
    item = publish_article(article, choice, config, state, published)
    print(json.dumps({
        "status": "published",
        "keyword": choice.keyword,
        "cluster": choice.cluster,
        "angle": choice.angle,
        "article": item["path"],
        "image": item["image_path"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"SEO generation failed: {error}", file=sys.stderr)
        raise
