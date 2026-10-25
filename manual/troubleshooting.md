# Troubleshooting

**A dashboard dot is red.** The service is down. Check it with
`systemctl status <service>` and its log with `journalctl -u <service> -e`.
For the wiki: `kiwix-serve` and `kiwix-library`.

**A new ZIM doesn't show up.** Make sure it ends in `.zim`, then run
`sudo systemctl restart kiwix-library` and check
`journalctl -u kiwix-library` for "skipping unreadable".

**Logging in on the text console.** The account is called `deck`; use the
password you chose at the first start.

**Something else.** Every system change can be undone — see
[Rebuilding](rebuilding.html).
