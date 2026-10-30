# Storage (content on several drives)

`modules/services/storage.nix` + `modules/services/content/app/{locations,library,drives}.py`
— where the box's content lives (ADR-0006). Wiki books and maps can live on **this device**
and on **added drives** (a big disk that stays plugged in). Services never see the drives:
they read one merged, checked **library**.

## Locations

Every location has the same tree:

    survival-kit.json   ← marker: {"format": 1, "name": "…"}
    wiki/               ← *.zim
    maps/               ← *.pmtiles
    models/             ← (unused: AI models stay in Ollama's own store, see below)
    .incoming/          ← uploads in progress

| Location | Tree |
|---|---|
| built-in | the Nix store (starter books, built-in maps) — read-only, not in the library |
| this device | `/var/lib/survival-kit/data/` |
| added drive | `/var/lib/survival-kit/drives/<uuid>/survival-kit/` — the drive's own root is mounted at `drives/<uuid>/` |

The box **never formats** a drive and never touches anything on it outside `survival-kit/`
(and `survival-kit-set-aside/`, see auto-resolve). A marker with a higher `format` than
this box knows → the drive is not used ("set up by a newer survival-kit").

## The library

`/var/lib/survival-kit/library` is a **symlink** to `.library-<time>/`, which holds
`wiki/<name>.zim` and `maps/<name>.pmtiles` — links to the copy **in use** of every book
and map. Kiwix (`kiwix-library`) and nginx (`maps.deck/imported/`) read only this.

`survival-kit-library.service` (`library.py`, oneshot, root, confined to
`/var/lib/survival-kit`) builds it:

1. scans every location: files with the right extension, under their **clean name** (the
   same rules as imports: `…_2026-01.zim` → `….zim`, `Austria.PMTILES` →
   `austria.pmtiles`); hidden files, other files and sub-folders are ignored;
2. **checks** each file with the upload checks — Kiwix must read a book, maps must pass
   `pmtiles.check`; a file named like the box's manuals is refused. Results are cached in
   `/var/lib/survival-kit/content/checks.json` by (real path, size, mtime), so a boot only
   checks new or changed files;
3. resolves names on several locations: **the newer copy wins** — a book's ZIM `date`
   (from Kiwix), a map's modification time; equal or unknown → this device, then drives in
   the order they were added. Others are `duplicate`, failures `invalid`;
4. builds a new `.library-*` folder of links, makes the linked files readable for everyone
   (Kiwix and nginx run unprivileged; on exFAT/NTFS the mount options do this), swaps the
   symlink with `os.replace` (readers see the old or the new index, never half), deletes the
   old folder;
5. writes `/var/lib/survival-kit/library.json` (every file with location, status, reason —
   what the content manager shows) and asks `kiwix-library` to reload.

**Auto-resolve** (content manager, per location) *moves* that location's `invalid` and
`duplicate` files to `survival-kit-set-aside/<date>/<kind>/` at the drive's root (this
device: `/var/lib/survival-kit/data/.set-aside/` — inside the data tree, because the content
manager's sandbox makes each writable path its own mount and a rename between two mounts
fails) — a rename on the same filesystem, never a delete; a name already there gets `-1`,
`-2`, …

## Added drives

The list is **runtime data**, not configuration — adding a drive never needs a rebuild:
`/var/lib/survival-kit/content/drives.json` (`[{uuid, fstype, name, added}]`, in add
order; in the content manager's own folder so it can rewrite it atomically).

`survival-kit-drives.service` (`drives.py mount-all`, oneshot, **not sandboxed** — a mount in
a private namespace would be seen by nobody else), at boot before the library and after
every Add / Forget / Reconnect:

- waits up to 10 s for listed drives that haven't shown up yet (USB at boot);
- unmounts anything under `drives/` that is no longer listed;
- per listed drive: present (`/dev/disk/by-uuid/<uuid>`)? A desktop mount
  (`/run/media/…`, from opening it in the file manager) is **taken over** (unmounted
  first); a mount anywhere else → refused. Then `mount` at `drives/<uuid>` and create/check
  the tree. One drive's trouble never stops the others; results go to
  `/run/survival-kit/drives.json` (`{uuid: {mounted, error}}`), which the library reads;
- a drive that is gone but still mounted (the kernel keeps a dead mount after a pull-out),
  or mounted from a device node it no longer has, is unmounted (`umount -l`) first;
- writes `/run/udev/rules.d/90-survival-kit-drives.rules`: per listed drive
  `UDISKS_IGNORE=1` (hidden from the desktop, so nobody "ejects" a drive the wiki reads
  from) and a rule that re-runs this service when the drive is pulled out or plugged in;
- writes its result atomically and asks the library to rebuild.

A damaged `drives.json` is reported (content manager page, journal) and never treated as an
empty list — nothing gets unmounted because the list can't be read.

Filesystems (`boot.supportedFilesystems`): ext4, btrfs, xfs, f2fs (`noatime`); exFAT and NTFS
(kernel `ntfs3`) with `uid=0,gid=0,dmask=022,fmask=133` — root writes, everyone reads.
FAT32 (4 GB file limit) and encrypted drives (LUKS, BitLocker) are listed with the reason
and can't be added. Offered at all: filesystems on disks the system doesn't use — a disk
with anything mounted outside `/run/media/` and `drives/` (the system disk, swap) is never
offered, free partitions included. `lsblk --json` is the source.

A drive pulled out while running: the udev rule re-runs the mounting, which clears the dead
mount and rebuilds the library — its books and maps disappear within seconds, the rest keeps
working. Plugged back in, it is mounted again the same way. Whether a drive is usable is
always checked **live** (its `/dev/disk/by-uuid` entry exists and our mount is in place),
not taken from the last mount run; the library also leaves out a location it can't read
(a dead mount answers I/O errors) instead of failing. *Reconnect* re-runs the mounting by
hand.

## AI models

Not on drives: Ollama has one model store and, with a model's files linked from a missing
drive, its model list fails for **every** model (HTTP 500) — tested 2026-10-30. Models stay
in `/var/lib/ollama/models` on this device.

## Testing

Unit tests: `test_locations.py`, `test_library.py`, `test_drives.py` (fake `lsblk` output, a
fake command runner) and the location parts of `test_content.py`/`test_server.py`. VM test
`checks/drives.nix`: three extra disks (empty ext4, pre-filled exFAT, FAT32) — add, import
to a drive, used in place, auto-resolve (drive and this device), hidden from udisks, reboot
with a listed drive missing, a real unplug (the disk removed from the PCI bus) and plug back,
forget.
