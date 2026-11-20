"""RSS Headlines MCP: merged, keyword-filterable headlines from a configurable set of RSS/Atom feeds.

Built for voice assistants: one call returns a few KB of compact JSON, newest first.
Configuration (environment):
  FEEDS_FILE   path to a feeds JSON file (default: the bundled feeds.json)
  NEWS_TZ      IANA zone for the `published` field (default: TZ, else UTC)
  CACHE_SECONDS  per-feed cache lifetime (default 300)
  HOST, PORT   bind address for streamable HTTP (default 0.0.0.0:8000); path /mcp
  MCP_TRANSPORT  streamable-http (default) or stdio
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from importlib import resources
from pathlib import Path
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import httpx
from mcp.server.fastmcp import FastMCP

UA = "Mozilla/5.0 (compatible; RSS-Headlines-MCP/1.0; +https://github.com/danielrosehill/RSS-Headlines-MCP)"
ATOM = "{http://www.w3.org/2005/Atom}"
DC_DATE = "{http://purl.org/dc/elements/1.1/}date"


@dataclass
class Feed:
    key: str
    name: str
    url: str
    default: bool = True
    tags: list[str] = field(default_factory=list)
    # Some feeds stamp local wall-clock time with a wrong offset (Jerusalem Post says "GMT" for
    # Israel time). tz_override reinterprets the stated wall-clock time in this IANA zone.
    tz_override: str | None = None


@dataclass
class Item:
    outlet: str
    title: str
    link: str
    published: datetime | None
    summary: str
    categories: list[str]


def load_feeds() -> list[Feed]:
    path = os.environ.get("FEEDS_FILE")
    if path:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        data = json.loads(resources.files("rss_headlines_mcp").joinpath("feeds.json").read_text(encoding="utf-8"))
    return [
        Feed(key=f["key"], name=f.get("name", f["key"]), url=f["url"],
             default=f.get("default", True), tags=f.get("tags", []), tz_override=f.get("tz_override"))
        for f in data["feeds"]
    ]


FEEDS = load_feeds()
TZ = ZoneInfo(os.environ.get("NEWS_TZ") or os.environ.get("TZ") or "UTC")
CACHE_SECONDS = int(os.environ.get("CACHE_SECONDS", "300"))
_cache: dict[str, tuple[float, list[Item]]] = {}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def clean(s: str | None) -> str:
    s = _TAG.sub(" ", s or "")
    return _WS.sub(" ", html.unescape(s)).strip()


def parse_date(s: str | None) -> datetime | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_feed(feed: Feed, raw: bytes) -> list[Item]:
    root = ET.fromstring(raw)
    out: list[Item] = []
    override = ZoneInfo(feed.tz_override) if feed.tz_override else None
    for el in root.iter("item"):  # RSS 2.0
        title = clean(el.findtext("title"))
        link = (el.findtext("link") or "").strip()
        if not title or not link:
            continue
        out.append(Item(
            outlet=feed.name, title=title, link=link,
            published=parse_date(el.findtext("pubDate") or el.findtext(DC_DATE)),
            summary=clean(el.findtext("description")),
            categories=[clean(c.text) for c in el.findall("category") if c.text],
        ))
    for el in root.iter(f"{ATOM}entry"):  # Atom
        title = clean(el.findtext(f"{ATOM}title"))
        link_el = el.find(f"{ATOM}link[@rel='alternate']")
        if link_el is None:  # Element truthiness is child count, so no `or` here
            link_el = el.find(f"{ATOM}link")
        link = link_el.get("href", "") if link_el is not None else ""
        if not title or not link:
            continue
        out.append(Item(
            outlet=feed.name, title=title, link=link,
            published=parse_date(el.findtext(f"{ATOM}published") or el.findtext(f"{ATOM}updated")),
            summary=clean(el.findtext(f"{ATOM}summary") or el.findtext(f"{ATOM}content")),
            categories=[c.get("term", "") for c in el.findall(f"{ATOM}category")],
        ))
    if override:
        for i in out:
            if i.published:
                i.published = i.published.replace(tzinfo=override)
    return out


async def fetch_feed(client: httpx.AsyncClient, feed: Feed) -> tuple[list[Item], str | None]:
    hit = _cache.get(feed.url)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1], None
    try:
        r = await client.get(feed.url)
        r.raise_for_status()
        items = parse_feed(feed, r.content)
    except Exception as e:  # one bad feed must not sink the call
        if hit:
            return hit[1], None
        return [], f"{feed.key}: {type(e).__name__}"
    _cache[feed.url] = (time.monotonic(), items)
    return items, None


def short(s: str, n: int) -> str:
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:") + "..."


def _json(obj: dict) -> str:
    # Compact on purpose: FastMCP would pretty-print a dict, about 15% more bytes per voice turn.
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def select_feeds(outlets: list[str] | None) -> list[Feed]:
    if not outlets:
        return [f for f in FEEDS if f.default]
    wanted = {o.strip().lower() for o in outlets}
    return [f for f in FEEDS
            if f.key.lower() in wanted or f.name.lower() in wanted or wanted & {t.lower() for t in f.tags}]


mcp = FastMCP(
    "rss-headlines",
    instructions="News headlines from configured RSS feeds. Call headlines() for a news summary or a topic "
                 "('Iran', 'hostages'); summarise the returned items, don't read links aloud.",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8000")),
    stateless_http=True,
    json_response=True,
)


@mcp.tool()
async def headlines(query: str | None = None, hours: int = 24, limit: int = 15,
                    outlets: list[str] | None = None) -> str:
    """Latest news headlines merged from the configured RSS feeds, newest first.

    query: optional keywords; every word must appear (case-insensitive) in the title, summary or
      categories, e.g. "Iran" or "hostage deal". Omit for general headlines ("summarise the news").
    hours: only items published in the last N hours (default 24, max 168).
    limit: max items returned (default 15, max 40).
    outlets: optional outlet keys, names or tags to restrict to (see outlets()); default = the default feeds.
    Returns {count, now, items: [{title, outlet, published, summary, link}], errors?}.
    """
    hours = max(1, min(int(hours or 24), 168))
    limit = max(1, min(int(limit or 15), 40))
    feeds = select_feeds(outlets)
    if not feeds:
        return _json({"count": 0, "items": [], "errors": [f"no feed matches outlets={outlets}; see outlets()"]})
    async with httpx.AsyncClient(timeout=12, follow_redirects=True, headers={"User-Agent": UA}) as client:
        results = await asyncio.gather(*(fetch_feed(client, f) for f in feeds))
    items = [i for its, _ in results for i in its]
    errors = [e for _, e in results if e]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items = [i for i in items if i.published and i.published >= cutoff]
    if query:
        terms = [t.lower() for t in re.findall(r"\w[\w'-]*", query)]
        items = [i for i in items
                 if all(t in f"{i.title} {i.summary} {' '.join(i.categories)}".lower() for t in terms)]

    seen: set[str] = set()
    uniq = []
    for i in sorted(items, key=lambda x: x.published, reverse=True):
        k = i.title.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    uniq = uniq[:limit]

    out = {
        "count": len(uniq),
        "now": datetime.now(TZ).strftime("%a %d %b %H:%M"),
        "items": [{
            "title": i.title,
            "outlet": i.outlet,
            "published": i.published.astimezone(TZ).strftime("%a %d %b %H:%M"),
            "summary": short(i.summary, 200),
            "link": i.link,
        } for i in uniq],
    }
    if errors:
        out["errors"] = errors
    return _json(out)


@mcp.tool()
def outlets() -> dict:
    """The configured feeds: key, name, whether included by default, and tags (usable in headlines(outlets=...))."""
    return {"outlets": [{"key": f.key, "name": f.name, "default": f.default, "tags": f.tags} for f in FEEDS]}


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "streamable-http")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
