# Content manager

`modules/services/content/` — <https://content.deck>: import wiki books, maps and AI models
through the browser's file dialog, list them with sizes, delete them, show disk use
(ADR-0004). On in both profiles; the maps part when [Maps](maps.html) is on, the models
part only when Ollama is on.

## Files

| File | What |
|---|---|
| `app/content.py` | All file logic: name rules, space check, streaming an upload to disk, `Shelf` (wiki books, maps), `Models` — no HTTP |
| `app/pmtiles.py` | Reads a map file's header and description; decides whether an import can be drawn here |
| `app/server.py` | The JSON API + the page (stdlib `http.server`); real helpers for Kiwix and Ollama |
| `app/static/` | `index.html` (template; the server fills in the lists) and `content.js` (imports, progress, confirmations) |
| `app/test_content.py`, `app/test_pmtiles.py`, `app/test_server.py` | Unit tests (`checks/content-unit.nix`) with stand-ins for Kiwix/Ollama |
| `app/pmtiles_fixture.py` | Writes tiny valid (or deliberately broken) map files — for the unit tests and the `services` VM test |
| `default.nix` | The systemd service, registry entry (port 8300), nginx settings |

Python **standard library only** (Python 3.13 has no `cgi` module, which is why uploads
are one file per request with the raw file as the body).

## API

| Request | Does |
|---|---|
| `GET /health` | `ok` (the dashboard dot) |
| `GET /api/status` | disk, wiki imports, built-ins (`replaced`, `protected`), maps + `map_builtins` (`null`/empty without the maps service), models (`null` on lite), `models_error` (set when Ollama doesn't answer — the rest of the page keeps working), locations |
| `GET /api/check?kind=&file=&size=[&model=]` | the stored name, whether it exists (`import`/`builtin`), space check — before uploading |
| `PUT /api/upload?kind=&file=[&model=]` | `kind` = `wiki`, `map` or `model`; body = the file; `Content-Length` required; answers `name`, `result` (`added`/`replaced`) and `note` (a doubt worth showing, or null) |
| `DELETE /api/wiki/<name>`, `/api/maps/<name>`, `/api/models/<name>` | delete |

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
- **Maps:** `.pmtiles` only, stored lower-case with `[a-z0-9._-]`; an import named like a
  built-in map replaces it on the map page (which prefers `/imported/`), deleting it
  brings the built-in back. `pmtiles.py` checks before the move: PMTiles **v3**, tile type
  **vector**, compression none or gzip (all pmtiles.js reads), file not shorter than any
  section the header declares, the Protomaps layers (`earth`, `water`, `roads`, `places`)
  in the description, and its `version` major = `MAP_SCHEME` (4, the Protomaps scheme the
  bundled style draws). Anything else is refused — such a map would draw nothing yet take
  its area away from the built-in maps; a Protomaps map without a `version` is accepted
  with a note. Nothing restarts — nginx lists the folder.
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
confined: `ProtectSystem=strict` with write access only to `zims/`, the maps folder
(`/var/lib/survival-kit/maps`, uploads in its hidden `.incoming/`) and its own state dir,
`ProtectHome`, `PrivateTmp`, `NoNewPrivileges`. Ollama keeps its models itself; the
service only talks to it.

Open to anyone who can reach the page (today: the box itself). A password option is in the
backlog — needed before hub mode.

## Adding a kind

A kind that is "files in a folder" is a `Shelf(dir, ext, builtins, protected, validate,
refresh, noun)` — as wiki books and maps are; write its `validate` (returns a note or
raises `Refused`) and a name rule. Anything else needs a class with `items()`,
`exists(name)`, `install(tmp, name)`, `delete(name)`, `used()` (like `Models`). Tests first;
then route it in `server.py` (`target()`, `do_DELETE`, the status and `render()`) and give
the service write access to its folder in `default.nix`.
