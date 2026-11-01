# Files (File Browser)

`modules/services/files/` + `modules/services/content/app/files_view.py` — a small personal
cloud at `https://files.deck` (ADR-0006 amendment): everyone signs up and keeps their own
files on this device or on an added drive; the box's wiki books and maps are there too,
read-only, to download. File Browser (nixpkgs `services.filebrowser`) on `127.0.0.1:8330`,
nginx in front (uploads of any size, streamed — like the content manager).

## A space

File Browser shows `/var/lib/survival-kit-files/view` (root's, 0755). Signing up makes
`view/users/<account>/` (`--createUserDir`) and scopes the account to it. What the person
sees there:

    This device/            ← /var/lib/survival-kit/data/files/<account>/      read-write
    <drive name>/           ← <drive>/survival-kit/files/<account>/            read-write
    Library/
      Built-in/wiki/<book>  ← the starter books (one bind per file)           read-only
      Built-in/maps/<map>   ← the built-in maps                                read-only
      This device/{wiki,maps,media}  ← /var/lib/survival-kit/data/{wiki,maps,media}  read-only
      <drive name>/{wiki,maps,media} ← <drive>/survival-kit/{wiki,maps,media}        read-only

Every entry is a **bind mount**, not a symlink: File Browser hides and refuses links that
point outside a person's space (tested 2026-10-30). The built-in folders are link farms
into the Nix store, so they are bound file by file. People's files live in the content tree
next to `wiki/` and `maps/` — on a drive in its `survival-kit/files/` folder, so they travel
with the drive. The top of a space is root's (0755): File Browser can't drop a file there
(403); people choose a location folder. The Library is a read-only mount: the kernel
refuses writes even for root. File Browser would answer those with **500** "read-only file
system" (it maps only permission errors to 403), so nginx answers **403** first: a regex
location for `/api/(resources|tus)/Library…` lets only GET/HEAD through, and a copy/move
whose `?destination=` points into `/Library` is refused at the server level.

**Links on a drive are never followed by root.** A drive is anyone's: a `survival-kit/`,
`files/`, `wiki/` or `maps/` that is a symlink (e.g. to `/var/lib/survival-kit`) would make
the root service chown and bind that place into someone's space — such a drive is left out
of Files (logged); a `files/<account>` link leaves out that one folder. Accounts that are
links in `view/users` (File Browser owns that folder) are skipped, and owners/modes are set
without following links.

Folder names: drives by their name from the content manager, made safe (no `/`, not hidden,
empty → `Drive`) and unique without regard to case (`Big`, `big (2)`); `Library`, `Built-in`
and `This device` are taken.

## Building the spaces

`survival-kit-files-view.service` (`files_view.py`, oneshot, root, **not sandboxed** — its
mounts must be seen system-wide) runs at boot (after the drives, before File Browser) and
whenever `survival-kit-files-view.path` sees a change in `view/users` (a sign-up) or in
`/run/survival-kit/drives.json` (a drive added, forgotten, pulled out, plugged back). It:

1. lists the accounts (folders in `view/users`) and the locations usable now
   (`library.current_locations`, the same live check as the library);
2. makes each person's folder on every location (`files/<account>/`, 0700, File Browser's)
   and makes each space's top root's — **changing only what isn't right yet**: the path unit
   watches `view/users`, and a run that touched it again would start itself forever;
3. compares the mounts it wants with the last run's (`/var/lib/survival-kit-files/view.json`
   — kept across reboots, so the first run after a boot removes the empty folders of drives
   that are gone)
   and with the kernel's (`/proc/self/mounts`): unwanted ones and **stale** ones go
   (`umount -l`, deepest first; a bind of a drive that was pulled out and plugged back
   points at the dead filesystem — device/inode differ from the source), then the missing
   ones are mounted (`mount --bind`, `-o ro` for the Library), parents first. A mount that
   fails is left out and tried again next run.

A trigger that comes *while* the service runs is folded into that run by systemd, so the
service repeats itself (up to 5 times) until the accounts and the drive state are the same
after a run as before it. `survival-kit-drives` is told (`OURS`) that mounts under the view
are the box's own: a drive replugged before the view took its binds down is not "in use".

File Browser's own unit is confined: `ProtectSystem=strict`, writable only
`view/` and its database folder, and `InaccessiblePaths=/var/lib/survival-kit` — it can't
see the content tree at all, only what is bound into the view. New binds still reach it:
its private mount namespace receives mounts from the system's (mount propagation).

**exFAT/NTFS drives** have no owners, so `chown` can't hand a person's folder to File
Browser. With Files on, `survival-kit-drives` mounts them with
`uid=0,gid=filebrowser,dmask=002,fmask=113` (`survivalKit.storage.filesGroup`): root and
File Browser's group write, everyone reads.

## Settings

File Browser keeps its settings in its database (`/var/lib/filebrowser/database.db`). The
unit's `preStart` sets them on every start (`filebrowser config init` the first time,
`config set` after): JSON logins, sign-up on, minimum password length 1 (user's call: any password; File Browser itself still refuses an
empty one and those on its built-in list of common passwords), new accounts may
create/rename/change/delete/download but **not** share (public links), run commands or
administer; dotfiles hidden, command runner off, branding "Files" without external links.
**Sign-up is patched** (`signup.patch`): File Browser turns a name into its home folder name
by dropping `..` and replacing other characters with `-`, and it would happily reuse a
folder that exists — `anna..b` and `annab`, or `anna b` and `anna-b`, would share one space.
The patch refuses (400) a name its folder name would change or that starts with `.`, and
(409) a name whose folder is already there. Check it still applies when File Browser is
updated. A database made with `config init` has no users — File Browser's quick setup (an admin
account with a printed password) never runs. Nobody is admin; there is no user management
page.

**Forgotten password:** `sudo survival-kit-files reset-password <name>` — asks twice
(not empty), stops File Browser (its database is locked while it runs), runs
`filebrowser users update <name> --password …` as the `filebrowser` user and starts it
again.

Health: `/health`. Logs: `journalctl -u filebrowser -u survival-kit-files-view`.

## Testing

Unit tests: `test_files_view.py` (folder names, wanted mounts, reconcile with a fake command
runner, personal folders, a second run changes nothing). Eval: `checks/eval-files.nix`. VM
test `checks/files.nix`: sign-up, private spaces, the Library read-only (the OS refuses, nothing
changes on disk), File Browser can't see the content tree, an exFAT drive as a folder, a real
unplug and plug back, the password reset, reboot.
