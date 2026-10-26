# Chat

`modules/services/chat/` — <https://chat.deck>, **full** profile only (needs Ollama and the
[Wiki lookup](lookup.html)). ADR-0005: the box enforces "wiki first"; the model only plans
and writes.

## Files

| File | What |
|---|---|
| `app/store.py` | SQLite (`/var/lib/survival-kit/chat/chats.db`, WAL): chats, messages, jobs |
| `app/worker.py` | The one worker: lookup → answer from articles → fallback; prompts and budgets |
| `app/server.py` | JSON API, live events (Server-Sent Events), the page; real Ollama/lookup helpers |
| `app/static/` | `index.html`, `chat.js` (model text inserted as text only, never HTML) |
| `app/test_*.py` | Unit tests (`checks/chat-unit.nix`) with stand-ins for the lookup and the model |

## A question's life

1. `POST /api/chats/<id>/ask` stores the question and queues a **job** (`queued`).
2. The worker takes the oldest queued job — **one at a time** on the whole box — and runs it
   (`running`): lookup ("Looking at the book map", "Searching …", "Reading 3 articles"),
   then "Writing the answer".
3. The answer prompt (`ANSWER_SYSTEM`) gives the model the articles and says: use only
   these, mention their titles, or reply exactly `NOT_IN_WIKI`. The first 16 characters are
   held back until the marker is ruled out, so it never shows.
4. Marker, no articles, or the lookup down → `FALLBACK_SYSTEM` (own knowledge); the answer
   starts with the notice "Not found in the wiki — this answer comes from the model's own
   training and may not be precise."
5. `done`: the answer is stored with its sources. Errors (model gone, Ollama down, empty
   answer) → `failed` with a readable message; the queue goes on.

The answer text is saved as it streams. A page follows a job via
`GET /api/jobs/<id>/events`: first a `replay` (state, last status, text so far, queue
position), then live `status` / `token` / `queue` / `done` / `error` events. Each token
carries `end` (its end position in the full text), so a reconnecting page never shows a
word twice. Closing the page doesn't stop the answer. After a restart, a `running` job is
marked "interrupted — ask again"; `queued` ones go on.

## API

`GET /api/models`, `GET|POST /api/chats`, `GET|PATCH|DELETE /api/chats/<id>`,
`POST /api/chats/<id>/ask`, `DELETE /api/jobs/<id>` (cancel a waiting question),
`GET /api/jobs/<id>/events`. Writes take JSON bodies only (a form on another site can't send
them). nginx: `proxy_buffering off` so tokens arrive live.

## Tuning

Budgets and prompts are constants at the top of `worker.py` and `lookup.py`. Small models
(3B) sometimes ignore the marker or answer from the articles badly — change the prompt
wording there and note the final wording here.
