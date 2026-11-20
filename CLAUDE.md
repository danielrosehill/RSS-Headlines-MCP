# RSS-Headlines-MCP: agent context

Release tier: **small** (`v1.0`, `v1.1`, ...).

- Python via `uv`. Server: `src/rss_headlines_mcp/server.py`; bundled feeds: `src/rss_headlines_mcp/feeds.json`.
- Keep it generic: no private hosts or deployment details here. Daniel's deployment (residencehome stack `news-mcp`, gateway upstream `news`) lives in the private `danielrosehill/news-mcp-deployment` and builds from a tag of this repo.
