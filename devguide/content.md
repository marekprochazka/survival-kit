# Content manager

`modules/services/content/` — <https://content.deck>: import wiki books and AI models
through the browser's file dialog, list them with sizes, delete them, show disk use
(ADR-0004). On in both profiles; the models part only when Ollama is on.

## Files

| File | What |
|---|---|
| `app/content.py` | All file logic: name rules, space check, streaming an upload to disk, `Wiki`, `Models` — no HTTP |
| `app/server.py` | The JSON API + the page (stdlib `http.server`); real helpers for Kiwix and Ollama |
| `app/static/` | `index.html` (template; the server fills in the lists) and `content.js` (imports, progress, confirmations) |
| `app/test_content.py`, `app/test_server.py` | Unit tests (`checks/content-unit.nix`) with stand-ins for Kiwix/Ollama |
| `default.nix` | The systemd service, registry entry (port 8300), nginx settings |

Python **standard library only** (Python 3.13 has no `cgi` module, which is why uploads
are one file per request with the raw file as the body).

## API

| Request | Does |
|---|---|
| `GET /health` | `ok` (the dashboard dot) |
| `GET /api/status` | disk, wiki imports, built-ins (`replaced`, `protected`), models (`null` on lite), `models_error` (set when Ollama doesn't answer — the rest of the page keeps working), locations |
| `GET /api/check?kind=&file=&size=[&model=]` | the stored name, whether it exists (`import`/`builtin`), space check — before uploading |
| `PUT /api/upload?kind=&file=[&model=]` | body = the file; `Content-Length` required |
| `DELETE /api/wiki/<name>`, `DELETE /api/models/<name>` | delete |

Refusals answer 400 (bad input), 403 (built-in or the box's own manuals) or 404, with
`{"error": "…"}` — the page shows the message as is. The API enforces every rule itself;
the page's dialogs are only for the person.

## Rules

- **Wiki names:** `.zim` only; Kiwix's date suffix `_YYYY-MM` is dropped (stable address,
  newer downloads replace older ones); other characters → `_`; no hidden names;
  `survival-kit` and `survival-kit-dev` refused.
- **Built-ins:** an import with a built-in's name replaces it — `kiwix-library` skips a
  starter book when `zims/` holds a file of the same name. Deleting the import brings it
  back. Built-ins themselves can't be deleted (they're in the Nix store).
- **Readable:** a book is checked with `kiwix-manage <throw-away catalog> add` *before* it
  is moved in; unreadable → refused and removed. (Two identical ZIM files under different
  names are one book to Kiwix.)
- **Models:** `.gguf` only; name from the file name (editable), Ollama-safe; added with
  `ollama create` from a temp Modelfile (as by hand), then the upload is deleted.
- **Space:** refused unless `size` (models: `2 × size`) plus a margin of
  `max(2 GiB, 5 % of the disk)` is free.

## Uploads and rights

nginx streams uploads to the service (`client_max_body_size 0`,
`proxy_request_buffering off`, 1 h timeouts). The service writes them to a temp file in
`zims/.incoming/` (wiki — same directory tree, so the final move is atomic; hidden, so
Kiwix ignores it) or `/var/lib/survival-kit/content/incoming/` (models). A cut-off upload
or a write error removes the temp file; leftovers are cleared at service start.

It runs as root — it writes into the wiki's folder and restarts `kiwix-library` — but
confined: `ProtectSystem=strict` with write access only to `zims/` and its own state dir,
`ProtectHome`, `PrivateTmp`, `NoNewPrivileges`. Ollama keeps its models itself; the
service only talks to it.

Open to anyone who can reach the page (today: the box itself). A password option is in the
backlog — needed before hub mode.

## Adding a kind

Add a class with `items()`, `exists(name)`, `install(tmp, name)`, `delete(name)`,
`used()` to `content.py` (tests first), route it in `server.py` (`target()`, `do_DELETE`,
the status and `render()`), give the service write access to its folder in `default.nix`.
