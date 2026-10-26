# Wiki lookup

`modules/services/lookup/` — what does the box's wiki say about a question? Used by the
[Chat](chat.html) before every answer, and by any MCP client. On both profiles (it needs no
model of its own — the planning step uses the chat's).

## Pipeline (`app/lookup.py`)

1. **Book map** — Kiwix's catalog (`/catalog/v2/entries`): per book the id (its
   `/content/<id>` path), title, summary, tags. Cached; the content manager calls
   `POST /invalidate` after imports and deletes, and a Kiwix error drops the cache too.
2. **Plan** — the model gets the map and the question (plus the last two questions, for
   follow-ups) and replies JSON `{"books": [...], "words": "2-4 keywords"}` (Ollama
   `format: json`, temperature 0.2). Unusable plan or no model → all books, the question's
   own words.
3. **Search** — `/search?books.name=…&pattern=…&format=xml`, top 5. Kiwix matches loosely
   (a common word like "first" matches a lot) — that's why the plan asks for precise keywords.
4. **Read** — the top 3 articles, HTML → text (scripts, styles, headers, category links
   dropped), at most **4000 characters** each.

Budget: 3 articles × 4000 characters + the conversation (last 6 messages, 4000 characters)
fit Ollama's `num_ctx = 8192` on an 8 GB machine.

## Front doors

- **HTTP** (127.0.0.1:8310, no vhost; `app/server.py`): `GET /books`, `POST /lookup
  {question, model, history}` → `{plan, hits, articles, error}`, `POST /invalidate`. Never
  fails on a Kiwix outage — it returns no articles and an `error` note.
- **MCP** (`app/mcp.py`, command **`survival-kit-wiki-mcp`**, JSON-RPC over stdio): tools
  `wiki_books`, `wiki_search {words, books?}`, `wiki_read {url}` (only links into this box's
  wiki). Here the *client's* model decides when to call the tools. Most MCP clients
  (oterm, mcphost, …) take a config entry of this shape:

        { "mcpServers": { "wiki": { "command": "survival-kit-wiki-mcp" } } }

The service runs as a dynamic user with no state and no write access; the fixtures in
`app/fixtures/` are real Kiwix 3.8.2 output.

## Adding a source

A new source (notes, maps, …) gets its own small lookup with the same shape —
`run(question, model, history) → articles [{title, url, text}]` — and the chat's worker asks
it next to the wiki.
