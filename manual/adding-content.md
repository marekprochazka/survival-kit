# Adding content

The wiki serves `.zim` files — packaged websites. Thousands exist at
<https://library.kiwix.org> (Wikipedia, Stack Exchange, medical guides, …);
download them while you have internet.

To add one:

1. Copy the file into `/var/lib/survival-kit/kiwix/zims/`
   (`sudo cp wikipedia.zim /var/lib/survival-kit/kiwix/zims/`).
2. Refresh the catalog: `sudo systemctl restart kiwix-library` (or reboot).

To remove one, delete the file and refresh the same way.
