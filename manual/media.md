# Media

The **Media** tile (<https://media.deck>) plays films, series and music — offline, in the
browser. It is **Jellyfin**. Everyone on the box sees the same films and music; each person
has their own account, so *Continue watching* and *already seen* are their own.

## Signing in

Sign in with the **name and password you chose at the very first start** of the box (the
same as for `sudo`). That account is the box's media **admin**: it can add the others.
Media allows fewer characters in names (letters, digits, spaces and `- ' . _ @ +`); if your
name had others, the first start showed the shortened name Media uses — e.g. *Zoë O'Brien!*
becomes *Zoë O'Brien*.

If you change the box's password later, Media keeps the old one — change it in Media too
(your picture at the top right → *Profile* → *Password*).

## Adding people

Jellyfin has no "sign up" button: the admin adds people.

1. Signed in as the admin: the menu (☰) → **Dashboard** → **Users** → **+**.
2. Type their name and a password, tick **Movies**, **Shows** and **Music** (or *Enable
   access to all libraries*), and **Create**.
3. In the new person's **Profile** settings, untick **Allow video playback that requires
   transcoding** — see *What plays* below for why — and **Save**.

They sign in with that name and password and can change the password themselves.

## Adding films, series and music

Media comes in through the [Content](content.html) page, like books and maps, and the
page **sorts it** into the right place. Under *Media* there are three forms:

- **A film** — choose the video file (and subtitle files, if you have them). The title is
  filled in from the file name; correct it and add the year. Media shows it as
  *Title (Year)*.
- **A season of a series** — choose the episode files, type the series name and the season
  number. Episodes are put in order by the number in their file names (`S01E03`, `1x03`);
  files without one may end up out of order.
- **An album** — choose the album's folder (or single tracks) and check its name. Artist,
  album and track order come from the **tags inside the music files**.

The import appears in Media within a minute. **Save new … to** at the top of the Content
page picks where it goes — films are big, so a [big drive](content.html#adding-a-big-drive)
is the usual place. Importing a film, season or album that is already there replaces it
(the page asks first).

**There is no internet**, so Media shows **no posters, plots or cast lists** — films get a
picture taken from the video, music the cover art inside the files (if any). The names you
type are what everyone sees.

## A drive with media already on it

A drive added on the Content page can already hold media; it is used **without copying**
if it is laid out like this, in its `survival-kit` folder:

```
survival-kit/media/movies/<Film title (Year)>/<Film title (Year)>.mkv
survival-kit/media/shows/<Series>/Season 01/<episodes>
survival-kit/media/music/<Album>/<tracks>
```

Other files beside them (posters, `.nfo` files, a `Sample` folder) are left alone. Name the
**video file** like the title — that is what Media shows. If the same film, season or album
is on two places, the **newer** copy is used; the other is shown as a duplicate and
*Auto-resolve* moves it aside (nothing is deleted). Pull the drive out and its media
disappears from Media until it is back; changes made while the box was off show up a minute
or two after it starts. Folders on the drive that are *links* (shortcuts) are ignored.

## What plays

Firefox plays video in **H.264**, **VP9** or **AV1** and sound in **AAC**, **MP3**, **FLAC**,
**Opus** or **Vorbis** — most `.mp4`, `.mkv` and `.webm` files. A second subtitle file
without a language in its name is kept as *…2.srt*. Sound it can't play
(**AC3**, **DTS** — common in films) is converted while you watch; that is light work.
**Video is never converted**: that would make an old laptop crawl. A film whose video
Firefox can't play (e.g. **HEVC / H.265**) shows an error instead. `.avi` and `.mov` files
are accepted but often don't play.

## Deleting

On the [Content](content.html) page each film, season and album has a **Delete** button.
Media itself doesn't delete files.

## What the box set up — and that you may change it

At the first start the box set Media up for an offline, slow-ish computer: no plugin
downloads, no posters or data from the internet, no video conversion, Media reachable only
from this box. The admin may change any of it in the *Dashboard* — the box never sets it
back. Turning internet features on only helps when the box is online; turning video
conversion on can make the computer slow while someone watches.

## If Media isn't set up

If the first start said *Media couldn't be set up now* (Media can take minutes to start
the first time on an older computer), finish it in a terminal:

    sudo survival-kit-media-setup

It asks for your box name and password and completes what is missing — the libraries,
the starting settings and the box's own rescan key. It changes nothing on a box where
Media is fully set up.

If instead opening Media shows Jellyfin's own setup pages, you can also fill them in (use
your box name and password), add three libraries **Movies** (*Movies*,
folder `/var/lib/survival-kit/library/media/movies`), **Shows** (*Shows*, `…/media/shows`)
and **Music** (*Music*, `…/media/music`), and then run `sudo survival-kit-media-setup` with
the same name and password so new imports show up by themselves. Until Media is set up,
its setup pages are open to anyone on this box — finish it soon.
