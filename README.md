# RSS-Headlines-MCP

A small MCP server that merges a configurable set of RSS/Atom feeds into one newest-first headline list,
optionally filtered by keyword. Built for voice assistants: one call returns compact JSON (about 6 KB for
15 items), so "summarise the news" or "what's happening with Iran" fits in a single turn.

The bundled feed list is Israeli English-language news (Times of Israel, Jerusalem Post, Haaretz, JNS,
Israel Hayom; Ynetnews off by default). Replace it with any feeds via `FEEDS_FILE`.

## Tools

### `headlines(query?, hours=24, limit=15, outlets?)`

| Arg | Type | Meaning |
| --- | --- | --- |
| `query` | string, optional | Keywords; every word must appear (case-insensitive) in the title, summary or feed categories. Omit for general headlines. |
| `hours` | int, 1-168 | Only items published in the last N hours. |
| `limit` | int, 1-40 | Max items returned. |
| `outlets` | list of strings, optional | Feed keys, names or tags to restrict to; default is every feed with `default: true`. |

Returns:

```json
{
  "count": 15,
  "now": "Fri 20 Nov 21:00",
  "items": [
    {"title": "...", "outlet": "Times of Israel", "published": "Fri 20 Nov 20:36",
     "summary": "first ~200 chars of the feed description", "link": "https://..."}
  ],
  "errors": ["jns: ConnectTimeout"]
}
```

`errors` appears only when a feed failed; the other feeds still return. Times are in `NEWS_TZ`.
Duplicate titles across outlets are dropped. Items without a parseable date are dropped.

### `outlets()`

Lists the configured feeds (`key`, `name`, `default`, `tags`).

## Configuration

| Env | Default | |
| --- | --- | --- |
| `FEEDS_FILE` | bundled `src/rss_headlines_mcp/feeds.json` | Your feed list (same shape) |
| `NEWS_TZ` | `TZ`, else `UTC` | Zone for `published` and `now` |
| `CACHE_SECONDS` | `300` | Per-feed cache; a failing feed falls back to its last good copy |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | Streamable HTTP, path `/mcp`, stateless, JSON responses |
| `MCP_TRANSPORT` | `streamable-http` | or `stdio` |

Feed entry:

```json
{"key": "jpost", "name": "Jerusalem Post", "url": "https://www.jpost.com/rss/rssfeedsfrontpage.aspx",
 "default": true, "tags": ["israel", "en"], "tz_override": "Asia/Jerusalem"}
```

`tz_override` is for feeds that stamp local time with a wrong offset. Found 2026-11-20: the Jerusalem Post
front-page feed labels Israel wall-clock time as `GMT` (an item at 19:47 "GMT" when it was 19:00 UTC), so
its times are reinterpreted as `Asia/Jerusalem`. The other bundled feeds carry correct offsets.

Feed notes (checked 2026-11-20): Times of Israel `/feed/` returns only ~13 items, so a 24 h window holds
most of a day only together with the other outlets; `https://www.timesofisrael.com/liveblog/feed/` is empty.
Ynetnews `StoryRss3082.xml` was last updated 2026-11-15, hence `default: false`. i24news has no working RSS.

## Run

```bash
uv sync
uv run rss-headlines-mcp                            # http://0.0.0.0:8000/mcp
MCP_TRANSPORT=stdio uv run rss-headlines-mcp        # for Claude Desktop / Claude Code stdio
docker compose up -d --build                        # 127.0.0.1:8000/mcp
```

Claude Code: `claude mcp add news -e MCP_TRANSPORT=stdio -- uvx --from git+https://github.com/danielrosehill/RSS-Headlines-MCP rss-headlines-mcp`

## Design

Stateless: no subscription database, feeds come from a JSON file. One call fetches the feeds in parallel
(cached), merges, filters by keyword and time, de-duplicates and trims, so the answer stays small enough for
a voice turn.

## License

MIT
