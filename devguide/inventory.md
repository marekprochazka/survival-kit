# Inventory (Homebox)

`modules/services/inventory/` — the household inventory at `https://inventory.deck`
(what, where, how much), via the nixpkgs `services.homebox` module (Homebox 0.25: one Go
binary with its web page built in, ~100 MB). On in both profiles.

## Settings (and why)

The upstream module already gives us the `homebox` user, a confined unit (`ProtectSystem`,
`PrivateUsers`, `UMask=0077`, …) and SQLite + files in `/var/lib/homebox/data`. On top:

- `HBOX_WEB_HOST = 127.0.0.1`, `HBOX_WEB_PORT = 7745`: only nginx talks to it.
- `HBOX_OPTIONS_ALLOW_REGISTRATION = true`: anyone at the box can sign up (upstream default
  in the module: off). Logins follow the box convention `<name>@inventory.deck`.
- `HBOX_OPTIONS_GITHUB_RELEASE_CHECK = false`: **the name Homebox 0.25 actually reads.** The
  nixpkgs module sets `HBOX_OPTIONS_CHECK_GITHUB_RELEASE`, which Homebox ignores. Without our
  line it would try to reach GitHub. (Homebox maps config fields to env names as
  `HBOX_<SECTION>_<FIELD>`; the field is `GithubReleaseCheck` in
  `backend/internal/sys/config/conf.go`.)
- `HBOX_OPTIONS_TRUST_PROXY = true`: Homebox's docs require it behind a reverse proxy. It
  takes the scheme (https) and the client address (for its login rate limit) from nginx's
  forwarded headers. That's safe because it listens on loopback only.
- `HBOX_OPTIONS_HOSTNAME = https://inventory.deck`: absolute links, e.g. invite links.
- `HBOX_WEB_MAX_UPLOAD_SIZE = 32` (MB; upstream 10), with `client_max_body_size 32m` on the
  vhost (nginx's default is 1 MB).
- Off by default and left off: OpenTelemetry, analytics, barcode lookup (needs a token and
  the internet), OIDC.

## Sharing: collections, no patch

Everyone in a Homebox **collection** (internally a *group*) sees the same items. A user can
be in several and switch. Others join with an **invite**: by registering through the invite
link, or later with *Join Existing Collection* (API: `POST /api/v1/groups/invitations/{id}`).
A user who registers **without** an invite gets a new empty collection of their own. There
is no setting to drop new users into a shared one, and we decided not to patch it: the
manual's *suggested setup* has the first person rename their collection "Household" and
invite the others.

## Backups

`backup-homebox` (timer 23:00, `Persistent`; never at boot, since that would overwrite a
good copy before anyone noticed a problem) runs `homebox-backup` as root:

1. No `homebox.db` yet (nobody signed up): nothing to do.
2. `sqlite3 homebox.db ".backup latest/homebox.db.tmp"`: a consistent copy while Homebox
   runs (the live DB is in WAL mode, so a plain `cp` could catch it mid-write). The copy is
   switched to `journal_mode=DELETE` so that opening it never creates `-wal`/`-shm` files
   beside it, then `mv`-ed over `latest/homebox.db`.
3. `rsync -a --delete --exclude 'homebox.db*' data/ latest/`: the attachment folders (one
   per collection).
4. `cp -al latest daily/<date>`: a **hard-link** copy; the newest 7 (by age) are kept.

**The rule that makes hard links safe:** nothing in `latest/` is ever changed in place,
because the same file is shared with every dated copy. The database is always a *new* file
(`mv`); rsync replaces a changed file by writing a temp file and renaming it (never use
`--inplace`); Homebox never edits an uploaded file. So 7 days cost about one copy of the
photos plus what changed. Same disk: protects against mistakes and a damaged database, not
against a dead disk.

### Restoring a backup

    sudo systemctl stop homebox
    sudo rsync -a --delete /var/backup/homebox/daily/<date>/ /var/lib/homebox/data/
    sudo chown -R homebox:homebox /var/lib/homebox/data
    sudo systemctl start homebox

Homebox turns WAL mode back on itself (its database address carries
`_pragma=journal_mode=WAL`).

## Tests

- `eval-inventory`: settings above, both profiles, registry entry, nginx body size, no
  `network-online` wait, backup timer only.
- `inventory` (VM): health and dashboard tile; the page and the scripts/styles it loads name
  no other hosts; sign-up + login through nginx; location + item with quantity, found by
  search; a 5 MB upload; backup integrity, not WAL, attachments present; a later backup
  leaves an older dated copy untouched; 7 kept.

Health: `/api/v1/status`. Logs: `journalctl -u homebox`, `journalctl -u backup-homebox`.
