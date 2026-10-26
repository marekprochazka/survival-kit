# Vaultwarden (Passwords)

`modules/services/vaultwarden/` — the password manager at `https://vault.deck`
(Bitwarden-compatible server + web vault), via the nixpkgs `services.vaultwarden` module.

- Listens on `127.0.0.1:8222`; nginx in front (`proxyWebsockets` for live sync).
- `DOMAIN = https://vault.deck` (links in the web vault). The web vault needs a secure
  context, so HTTPS is a prerequisite — see [HTTPS](tls.html).
- `SIGNUPS_ALLOWED = true`: anyone at the box can create an account. No `ADMIN_TOKEN`, so
  the `/admin` page is off.
- **Logins are email-shaped.** The email is the account's identity and the salt of the
  key derivation (master password + email → encryption key), so it can't be a plain
  username. The web vault's validator also wants a dotted domain (`…\.[a-zA-Z]{2,}$`):
  `anna@deck` is refused, `anna@vault.deck` works. The box's convention is
  `<name>@<service address>` (see [Services](services.html)); nothing is ever mailed — there
  is no mail server and no SMTP settings.
- Data: `/var/lib/vaultwarden` (SQLite, mode 0700). Daily backup (timer
  `backup-vaultwarden`, 23:00, `Persistent` → at the next boot if missed): upstream's
  script writes one copy to `/var/backup/vaultwarden/latest`, then our `ExecStartPost`
  (`vaultwarden-keep-daily`, as root) copies it to `daily/<date>` and keeps the 7 newest
  (by age, so a wrong clock can't delete the newest). Upstream also runs the backup at
  every boot — switched off (`wantedBy = mkForce [ ]`): it would overwrite a good copy
  before anyone noticed a problem. Same disk: no protection against a dead disk.
- Upstream's `network-online.target` dependency is removed: a loopback-only service on an
  offline box shouldn't wait for the network.
- Health: `/alive`. Logs: `journalctl -u vaultwarden`.
