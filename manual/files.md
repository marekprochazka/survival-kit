# Files

The **Files** tile (<https://files.deck>) is your own small cloud on this box: keep
documents, photos and anything else here, and download the box's wiki books and maps. It
works without internet.

**First use.** Open Files and choose **Sign up**. As the name, use your name followed by
`@files.deck`, e.g. **`anna@files.deck`** (the box's convention for logins — see
[What's on this box](whats-on-this-box.html)). Use only letters, digits and `@ _ . -` in
the name (not a `.` first, no `..`). Any password works, except an empty one and very
common ones like `password123`. Everyone at this box can make their own account; your
files are yours — others can't see them.

**Your folders.** After logging in you see:

- **This device** — your files on this computer;
- one folder per **big drive** added in [Content](content.html) (e.g. **Big**) — your
  files on that drive. Use it for things that don't fit on the computer;
- **Library** — the box's wiki books and maps, to download (e.g. to copy a book to a
  stick). Read-only: they are managed in [Content](content.html).

Put files into one of these folders — the top level itself takes nothing.

**When a drive is unplugged** its folder disappears until it is plugged back in; your files
stay on the drive (in its `survival-kit/files/` folder). **Forget** in Content stops using
the drive, but your files stay on it as well.

**Forgotten password?** Ask whoever looks after the box to run, in a terminal:

    sudo survival-kit-files reset-password anna@files.deck

and type a new password twice. Files is off for a few seconds while it changes.

Using Files from phones and other computers comes with the planned Wi-Fi hub mode.
