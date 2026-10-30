# Content

The **Content** tile (<https://content.deck>) brings new wiki books, maps and AI models onto
the box from a USB stick or a disc, keeps books and maps on this device or on a big drive
that stays plugged in, shows how much space is used, and removes things you no longer need.

## Importing

1. Plug in the stick (or insert the disc) and open **Content**.
2. Pick where new books and maps go: **Save new books and maps to** (this device or an
   added drive — the one with the most free space is chosen for you).
3. Under *Wiki books*, choose **Import wiki files** (or **a folder** to take every `.zim` in
   it); under *Maps*, choose **Import map files** (`.pmtiles` — see
   [Getting more maps](maps.html#getting-more-maps)); under *AI models*, choose
   **Import a model** (a `.gguf` file).
4. In the file dialog, click your stick or disc in the side panel — that opens it — and
   pick the files.
5. Each file shows a progress bar, then a result. Models also ask for a name first
   (a suggestion is filled in) and take a minute after the upload while they are added.
6. Reload the page to see the updated lists.

Before anything is copied, the box checks there is enough space where it goes (it always
keeps at least 2 GB free; a model needs about twice its size for a moment). AI models are
always stored on this device.

**Newer versions.** Kiwix downloads carry a date in their name (`…_2026-12.zim`); the box
stores them without it, so a newer download replaces the older one — it asks first. While
the new file uploads, the old one stays until the new one is complete — so replacing a big
book needs room for the new one too.

**Books that came with the box** (shown in grey) can be replaced the same way: importing a
newer Arch Wiki replaces the built-in one, after you confirm. Delete the import and the
built-in one is back. The box's own manuals can't be replaced. **Maps** work the same way:
a map named like a built-in one (`czechia.pmtiles`) replaces it until you delete the import.

**Maps are checked** before they are added: the file must be a Protomaps *vector* map in
PMTiles format, version 4 (what this box draws). Picture (raster) maps, maps from other
map makers (e.g. OpenMapTiles), other versions and files cut off while copying are refused
with the reason.

## Adding a big drive

A small notebook can keep its big books and maps on a drive that stays plugged in.

1. Plug the drive in and open **Content**. Under *Drives*, the drive is listed under
   **Drives you can add**.
2. Click **Add** and give it a name. The box **never formats** a drive: it creates a
   `survival-kit` folder on it (or uses the one already there) and leaves everything else
   alone.
3. From now on the drive is used at every start, and you can save imports to it.

Drives in **FAT32** format can't be added (they can't hold files over 4 GB) — use exFAT,
NTFS or ext4. Encrypted drives aren't supported yet.

**A drive with content already on it** — e.g. from another survival-kit box — is used as it
is: its books and maps appear right away. Each file is checked like an import; files the
box can't use are marked *invalid*, and if this box already has the same book or map, the
**newer** copy is used and the other is marked *duplicate — not in use*. **Auto-resolve**
moves all such files into a `survival-kit-set-aside` folder on the drive — nothing is
deleted.

**Unplugged?** Its books and maps disappear after a few seconds, and come back by themselves
when you plug the drive in again (if not, click **Reconnect**). **Forget** stops using a
drive for good; its files stay on it.

## Deleting and disk space

Each imported book, map and model has a **Delete** button (it asks first); it deletes that
one copy, wherever it is (the *Where* column). Books and maps that came with the box can't
be deleted. *Drives* shows the free space of this device and each added drive.

On boxes installed as **lite**, there is no AI models section.

Anyone who can open this page can import and delete — today that is only this box itself.
