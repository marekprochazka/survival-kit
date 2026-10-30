# Kiwix (the offline wiki)

`modules/services/kiwix/` — the wiki at `https://wiki.deck`, served by `kiwix-serve` from
`.zim` files (packaged websites).

## How it runs

- `services.kiwix-serve` (from nixpkgs) on `127.0.0.1:8080`, reading the catalog
  `/var/lib/survival-kit/kiwix/library.xml`, with `--monitorLibrary`.
- **`kiwix-library.service`** rebuilds that catalog **from scratch** at every boot (and when
  restarted): it adds every bundled book and every book in the content library,
  `/var/lib/survival-kit/library/wiki/` — links to the books in use on this device and on
  added drives, already checked and made readable (see [Storage](storage.html)). It runs
  after `survival-kit-library.service`.
  - Each file is added on its own; one that fails anyway (a drive pulled out since) is
    skipped with "kiwix-library: skipping unreadable …" in its log — one bad file never
    takes the wiki down.
  - The new catalog is written to a temp file and renamed into place (atomic); the temp
    file is removed if anything fails.
  - After a successful rebuild it restarts kiwix-serve (`--monitorLibrary` alone misses a
    second change within the same second).
  - A built-in book is skipped when the library holds a book with the same file name
    ("built-in … replaced by import") — see [Content manager](content.html).
  - kiwix-serve only *wants* kiwix-library: if a rebuild fails, the wiki keeps running on
    the last good catalog.

## Books and URLs

A book's URL is its **file name**: `x.zim` → `https://wiki.deck/content/x`. Bundled books
are therefore linked under clean names (`pkgs.linkFarm`), not their Nix store paths.

Bundled ("starter content", option `survivalKit.services.kiwix.starterContent`):

- `zims.nix` — downloaded ZIMs pinned by URL + hash: Arch Wiki, man pages, Nix, bash, git.
  `download.kiwix.org` keeps only recent releases, so a pinned URL eventually disappears:
  boxes and ISOs already built are fine, but a fresh rebuild elsewhere then needs a newer
  date + hash (`nix store prefetch-file <url>` prints the hash).
- `pkgs/books.nix` — the manual and this guide, built from Markdown (`manual/`,
  `devguide/`) with `lowdown` and `zimwriterfs`.

## Adding content by hand

    sudo cp something.zim /var/lib/survival-kit/data/wiki/
    sudo systemctl restart survival-kit-library

(it checks the book and reloads Kiwix). Usually: the [Content manager](content.html).
