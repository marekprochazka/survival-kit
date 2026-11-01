# Media (Jellyfin)

`modules/services/media/` — <https://media.deck>: **Jellyfin** 10.11 (nixpkgs) for films,
series and music, offline, in both profiles. The media lives in the content tree on every
location (`media/`, see [Storage](storage.html)) and comes in through the
[Content manager](content.html); Jellyfin only reads it. Spec
`docs/specs/2026-11-01-media.md`.

## Files

| File | What |
|---|---|
| `default.nix` | `services.jellyfin`, the first `network.xml`, the slice, the registry entry (port 8096, order 18), the library's rescan settings, `survival-kit-media-setup` |
| `app/setup.py` | The one-time setup (stdlib): wizard, owner, libraries, starting settings, the box's key |
| `app/test_setup.py` | Unit tests against a fake Jellyfin (`checks/media-unit.nix`); request shapes captured from a real 10.11.11 |

## How media reaches Jellyfin

Three libraries point at the library index: **Movies** →
`/var/lib/survival-kit/library/media/movies`, **Shows** → `…/media/shows`, **Music** →
`…/media/music`. The index holds links to the item folders on whichever location they are
(a series folder holds links to its seasons). Jellyfin follows the links. An item's index
path doesn't change when the index is rebuilt, so watch progress stays (VM-tested).

**Rescans:** Jellyfin's own file watching is off (it misses changes behind links and on
drives). After every import, delete or drive change the content manager rebuilds the
library, and `library.py` then calls `POST /Library/Refresh` with **the box's key**
(`/var/lib/survival-kit/media/api-key`, root-only, env `MEDIA_KEY_FILE`). No key (the owner
set Jellyfin up by hand) → no call; Jellyfin's scheduled scan or *Scan All Libraries* picks
the change up. At boot the library runs before Jellyfin answers, so
**`survival-kit-media-rescan.service`** (wanted by and after `jellyfin.service`, root only
to read the key) runs `library.py notify-media` after every Jellyfin start: it retries
until Jellyfin takes the request (up to 10 min) — `/health` already says *Healthy* while
everything else still answers 503 during startup. Jellyfin has no limited keys: this one could do anything an admin can, which
is why only root can read it and only the library uses it.

**Titles offline:** with no internet metadata, Jellyfin names a film after its **video
file** (`The Kid (1921).mkv` → "The Kid (1921)"; when the file name differs from the
folder's it uses the file name, VM-tested), a series after its folder, music after the
tags in the files. Imports name the video after the title the person typed.

## The one-time setup

First boot (see [First boot](firstboot.html)) pipes the owner's name and password into
`survival-kit-media-setup` (stdin only). `setup.py`:

1. waits (up to 5 min each, a first start on an old laptop is slow) for the index folders
   `movies/ shows/ music/` and for Jellyfin to answer (`GET /System/Info/Public`, a dot
   every 10 s); from then on one **overall limit** of 5 min bounds every call. If
   `StartupWizardCompleted` is true **and** the key file exists it changes nothing
   (**exit 2**); wizard done but no key = a setup that stopped half-way: it **resumes** —
   skips the wizard, signs in with the given name and password (another password → a clear
   error) and does only what is missing (libraries that don't exist yet, then the rest);
2. the wizard: `POST /Startup/Configuration` (English, server name `survival-kit`),
   `GET` + `POST /Startup/User` (the name — cleaned to what Jellyfin accepts: letters of any
   script, digits, space and `- ' . _ @ +`; the console says when it changed — and the
   password), `POST /Startup/RemoteAccess` (remote access and port mapping off),
   `POST /Startup/Complete`;
3. signs in (`/Users/AuthenticateByName`) and creates the three libraries
   (`POST /Library/VirtualFolders`) with: no metadata fetchers (all of them are internet
   services), only the local image fetchers (*Embedded Image Extractor*, *Screen Grabber*,
   *Image Extractor*), no metadata savers, real-time monitor off, trickplay and chapter
   image extraction off (heavy ffmpeg work), automatic refresh off;
4. the owner's policy: **video transcoding off**, sound transcoding and remuxing on;
5. server: plugin repositories emptied; network: auto-discovery and UPnP off;
6. `POST /Auth/Keys?app=survival-kit`, reads the key back, writes it root-only (temp file
   → rename), asks for a first rescan. **Exit 0**, or **3** when the name had to be
   shortened (the note is printed; first boot then waits for Enter); any failure → one
   line, **exit 1** (first boot says to run `sudo survival-kit-media-setup`, which asks for
   the name and password when run in a terminal).

**Set once (user's decision):** nothing re-applies these settings. The owner is a Jellyfin
admin and may change anything (even turn internet metadata on); a restart keeps it
(VM-tested). Jellyfin has **no default policy for new users**, so accounts the owner adds
may transcode video unless the box's manual step (untick it) is followed.

**Before setup** Jellyfin has its own password-less admin (named after the service user):
whoever reaches the setup wizard owns Jellyfin. It listens on 127.0.0.1 only and first boot
finishes the wizard, so normally the window is short and local — but if first boot's setup
failed *before* the wizard, it stays open until the owner finishes it. **Hub mode must
account for this** (e.g. not open Media to the network before setup is complete).

## Service settings

- `network.xml` is written by `preStart` **only when missing** (127.0.0.1, no UPnP, no
  discovery, no remote access) — a fresh Jellyfin would listen on every interface. The
  firewall stays closed for 8096 either way; nginx is the way in.
- Upstream orders Jellyfin after `network-online.target`; cleared (offline box).
- `Slice = background.slice` (see [Base](base.html)) and best-effort I/O 6: scans and sound
  conversion give way to the desktop.
- Memory: about **155 MB** after scanning a few items (VM test).

## Testing

`media-unit` (setup sequence, name cleaning, exit codes), `eval-media` (both profiles,
registry, port closed, slice, network.xml once, library env), `firstboot-script` (the
hand-over), `content-unit` (names, sniffing, scan, shelf, API) and the VM test
`checks/media.nix`: setup with a non-ASCII name, libraries and settings, imports of a film,
a film with AC3 sound and an album through the Content API, a folder already in place with
extra files and a `:` in its name, progress across a library rebuild, a changed setting
across a restart, delete. Playback in Firefox is checked by hand (VirtualBox).
