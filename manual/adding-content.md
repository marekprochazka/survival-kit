# Adding content

The wiki serves `.zim` files — packaged websites. Thousands exist at
<https://library.kiwix.org> (Wikipedia, Stack Exchange, medical guides, …);
download them while you have internet.

The easy way: the **Content** tile — see [Content](content.html).

By hand, in a terminal:

1. Copy the file into `/var/lib/survival-kit/data/wiki/`
   (`sudo cp wikipedia.zim /var/lib/survival-kit/data/wiki/`) — or into the
   `survival-kit/wiki/` folder of an added drive.
2. Refresh: `sudo systemctl restart survival-kit-library` (or reboot).

To remove one, delete the file and refresh the same way.

**Maps** (`.pmtiles`) come in through the Content tile too; how to make one for any area
is in [Maps](maps.html#getting-more-maps).
