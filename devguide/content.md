# Content manager

`modules/services/content/` — <https://content.deck>: import wiki books, maps, languages,
media and AI models through the browser's file dialog, list them with sizes, delete them, show disk use
(ADR-0004), on this device or on an added drive, and add/forget drives (ADR-0006, see
[Storage](storage.html)). On in both profiles; the maps part when [Maps](maps.html) is on,
the models part only when Ollama is on, the media part when [Media](media.html) is on.

## Files

| File | What |
|---|---|
| `app/content.py` | All file logic: name rules, space check, streaming an upload to disk, `Shelf` (wiki books, maps, on all locations), `Models` — no HTTP |
| `app/locations.py`, `app/library.py`, `app/drives.py` | Locations, the library (checks, newer-wins, index, set-aside, `Places`), drives — see [Storage](storage.html) |
| `app/media.py` | Media: name rules (real letters kept), file sniffing, film title suggestion, the layout scan (`scan_items`) and `MediaShelf` (batch imports, delete) |
| `app/pmtiles.py` | Reads a map file's header and description; decides whether an import can be drawn here |
| `app/server.py` | The JSON API + the page (stdlib `http.server`); real helpers for Kiwix and Ollama |
| `app/static/` | `index.html` (template; the server fills in the lists) and `content.js` (imports, progress, confirmations) |
| `app/test_*.py` | Unit tests (`checks/content-unit.nix`) with stand-ins for Kiwix/Ollama |
| `app/pmtiles_fixture.py` | Writes tiny valid (or deliberately broken) map files — for the unit tests and the `services` VM test |
| `default.nix` | The systemd service, registry entry (port 8300), nginx settings |

Python **standard library only** (Python 3.13 has no `cgi` module, which is why uploads
are one file per request with the raw file as the body).

## API

| Request | Does |
|---|---|
| `GET /health` | `ok` (the dashboard dot) |
| `GET /api/status` | disk (this device), `locations` (id, name, free/total, use), `drives` (`added` with mounted/error, `available` with refusal), wiki/maps items (every copy: `location`, `file`, `status` in_use/duplicate/invalid, `reason`), built-ins (`replaced`, `protected`), `map_builtins` (`null`/empty without the maps service), models (`null` on lite), `models_error` (set when Ollama doesn't answer — the rest of the page keeps working) |
| `GET /api/check?kind=&file=&size=[&to=][&model=]` | the stored name, whether it exists (`import`/`builtin`), space check on location `to` (default `device`) — before uploading |
| `PUT /api/upload?kind=&file=[&to=][&model=]` | `kind` = `wiki`, `map` or `model`; body = the file; `Content-Length` required; saved to location `to` (models: always this device); answers `name`, `result` (`added`/`replaced`) and `note` (a doubt worth showing, or null) |
| `DELETE /api/wiki/<name>[?at=&file=]`, `/api/maps/<name>[?at=&file=]`, `/api/models/<name>` | delete one copy: the one on location `at` (named `file`), else the one in use |
| `GET /api/media/suggest?file=` | a film's title and year guessed from its file name (for the form) |
| `POST /api/media/begin?type=&size=[&to=]` (type film, series or music) + `title`, `year` / `series`, `season` / `name` | starts a batch: the item key (`movies/The Kid (1921)`, `shows/S/Season 01`, `music/A`), whether it exists; space checked on the **total** |
| `PUT /api/media/upload?batch=&file=` | one file of the batch (`file` may be `CD1/01.flac` for music); checked by extension and content (`media.sniff`); more bytes than announced cancels the batch |
| `POST /api/media/finish?batch=`, `/api/media/cancel?batch=` | finish: the batch must have its video (film: exactly one) or audio, then it is renamed into place — only now does the item exist; cancel: staging removed |
| `DELETE /api/media/<item>[?at=]` | delete a film, season (the series folder goes with its last season) or album — only a real folder inside that location's `media/` |
| `POST /api/resolve?at=` | auto-resolve: move that location's invalid and duplicate files out of the tree |
| `POST /api/drives/add?uuid=[&name=]`, `/api/drives/<uuid>/forget`, `/api/drives/<uuid>/reconnect` | add a drive (refused: unknown, used by the system, FAT32/encrypted, already added); forget (files stay); mount again |

Refusals answer 400 (bad input), 403 (built-in or the box's own manuals) or 404, with
`{"error": "…"}` — the page shows the message as is. The API enforces every rule itself;
the page's dialogs are only for the person.

## Rules

- **Wiki names:** `.zim` only; Kiwix's date suffix `_YYYY-MM` is dropped (stable address,
  newer downloads replace older ones); other characters → `_`; no hidden names;
  `survival-kit` and `survival-kit-dev` refused.
- **Built-ins:** an import with a built-in's name replaces it — `kiwix-library` skips a
  starter book when the library holds a book of the same name. Deleting the import brings it
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
  with a note. The library is rebuilt; nginx lists its folder.
- **Models:** `.gguf` only; name from the file name (editable), Ollama-safe; added with
  `ollama create` from a temp Modelfile (as by hand), then the upload is deleted.
- **Space:** refused unless `size` (models: `2 × size`) plus a margin of
  `max(2 GiB, 5 % of the disk)` is free — on the chosen location's disk.
- **Media:** a batch is staged in the location's `.incoming/media-<batch>/` and moved into
  place with renames only (an old copy is renamed aside first, then removed), so a cut-off
  import leaves nothing; staging is cleared at service start. Names keep their real letters
  (accents, other scripts, spaces, parentheses — they are the titles Jellyfin shows);
  `/ \ : * ? " < > |` and control characters are replaced or dropped, at most 200 bytes. A
  film's video is renamed to the item (`The Kid (1921).mkv`), subtitles keep a language tag
  (`.cs.srt`). The page skips files of other types in a music folder.
- **Replacing:** an import replaces the copy of that name **in use**, wherever it is;
  duplicates on other locations are left alone. Delete removes only the copy clicked.

## Uploads and rights

nginx streams uploads to the service (`client_max_body_size 0`,
`proxy_request_buffering off`, 1 h timeouts). The service writes them to a temp file in
the chosen location's `.incoming/` (same filesystem, so the final move is atomic; hidden,
so the library ignores it) or `/var/lib/survival-kit/content/incoming/` (models). A cut-off
upload or a write error removes the temp file; leftovers are cleared at service start.

It runs as root — it writes into the content trees and restarts the drive and library
units — but confined: `ProtectSystem=strict` with write access only to its own state dir
(incl. `drives.json`), `/var/lib/survival-kit/data`, `/var/lib/survival-kit/drives` (drives
mounted later show up inside, tested); `ProtectHome`,
`PrivateTmp`, `NoNewPrivileges`. Ollama keeps its models itself; the service only talks to it.

Open to anyone who can reach the page (today: the box itself). A password option is in the
backlog — needed before hub mode.

## Adding a kind

A kind that is "files on the locations" is a `Shelf(places, kind, builtins, protected,
validate, refresh, noun)` — as wiki books and maps are: add its folder to `locations.DIRS`
and `KINDS` (extension + name rule), its check to `library.real_check`, and its link folder
to the library; write its `validate` (returns a note or raises `Refused`). Anything else
needs a class with `items()`, `exists(name)`, `install(tmp, name)`, `delete(name)`,
`used()` (like `Models`). Tests first; then route it in `server.py` (`target()`,
`do_DELETE`, the status and `render()`).
