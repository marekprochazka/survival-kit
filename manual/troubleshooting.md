# Troubleshooting

**A dashboard dot is red.** The service is down. Check it with
`systemctl status <service>` and its log with `journalctl -u <service> -e`.
For the wiki: `kiwix-serve` and `kiwix-library`; for Passwords: `vaultwarden`.

**A new ZIM doesn't show up.** Make sure it ends in `.zim`, then run
`sudo systemctl restart kiwix-library` and check
`journalctl -u kiwix-library` for "skipping unreadable".

**The Media dot is red.** Media (Jellyfin) needs **at least 2 GB free** on this device and
won't start with less. Free some space (delete things you don't need on the
[Content](content.html) page, or move big films to an added drive), then
`sudo systemctl restart jellyfin`. If it was never set up, see
[Media](media.html#if-media-isnt-set-up).

**Logging in on the text console.** The account is called `deck`; use the
password you chose at the first start.

**A file in the wiki folder is "ignored".** Only files ending in `.zim` are added. Rename
`.ZIM` to `.zim`; split downloads (`.zimaa`, `.zimab`, …) must be joined first:
`cat file.zima* > file.zim`.

**Something else.** Every system change can be undone — see
[Rebuilding](rebuilding.html).
