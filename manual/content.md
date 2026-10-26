# Content

The **Content** tile (<https://content.deck>) brings new wiki books and AI models onto the
box from a USB stick or a disc, shows how much disk space is used, and removes things you
no longer need.

## Importing

1. Plug in the stick (or insert the disc) and open **Content**.
2. Under *Wiki books*, choose **Import wiki files** (or **a folder** to take every `.zim` in
   it); under *AI models*, choose **Import a model** (a `.gguf` file).
3. In the file dialog, click your stick or disc in the side panel — that opens it — and
   pick the files.
4. Each file shows a progress bar, then a result. Models also ask for a name first
   (a suggestion is filled in) and take a minute after the upload while they are added.
5. Reload the page to see the updated lists.

Before anything is copied, the box checks there is enough space (it always keeps at least
2 GB free; a model needs about twice its size for a moment).

**Newer versions.** Kiwix downloads carry a date in their name (`…_2026-12.zim`); the box
stores them without it, so a newer download replaces the older one — it asks first.

**Books that came with the box** (shown in grey) can be replaced the same way: importing a
newer Arch Wiki replaces the built-in one, after you confirm. Delete the import and the
built-in one is back. The box's own manuals can't be replaced.

## Deleting and disk space

Each imported book and model has a **Delete** button (it asks first). Books that came with
the box can't be deleted. The line at the top shows free space and what the wiki and the AI
models take.

On boxes installed as **lite**, there is no AI models section.

Anyone who can open this page can import and delete — today that is only this box itself.
