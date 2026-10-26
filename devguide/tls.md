# HTTPS and the box's certificates

`modules/tls/` — every site on the box (`https://deck`, `https://wiki.deck`, …) is served
over HTTPS, with certificates made **on the box itself**. Plain `http://` answers with a
redirect (301) to `https://`, so old links and typed addresses keep working.

## Why HTTPS on an offline box

Browsers enable some features only in a *secure context* (HTTPS, or `localhost`). The
Bitwarden web vault ([Passwords](vaultwarden.html)) needs the browser's crypto API, so over
plain `http://vault.deck` it refuses to work. Instead of a special case, every site is HTTPS.

## The padlock: the box is its own certificate authority

A browser trusts an HTTPS site only if a **certificate authority (CA)** it trusts has
signed the site's certificate. Public CAs can't sign for `.deck` (not a real top-level
domain) — and there is no internet anyway. So the box is its own CA:

- `survival-kit-tls.service` (`modules/tls/tls.sh`, openssl) runs at every boot, before nginx.
- **The CA** (`ca.key`, `ca.crt`) is created once, when missing — and never replaced
  automatically: a new CA would break trust everywhere the old one was installed.
- **The site certificate** (`deck.crt`) carries every name explicitly: `deck`, each
  registered `<sub>.deck`, and `<hostname>.local`. (A wildcard `*.deck` does not work
  under a one-label domain.) It is re-issued when the names change (a new service), when
  it doesn't verify for the current clock, or when key and certificate don't belong
  together (e.g. a power cut between writing the two).
- Firefox trusts the CA through the policy `Certificates.Install` → the padlock, no warning.

## Safety: name constraints

A CA that Firefox trusts could, in principle, vouch for any site — your bank too. Ours
carries a critical **name constraint**: it may only vouch for `deck`, `*.deck` and
`<hostname>.local`. A certificate for any other name, even one signed with this CA's key,
is rejected ("permitted subtree violation"). The services VM test checks exactly that.

## The clock

Old machines often boot with a wrong clock (dead CMOS battery). Normal certificates last
about a year and would look "not yet valid" or "expired". Ours are valid from 2000 to 2100.
(The ~1-year limit is a rule for public CAs, not for one you install yourself; the desktop
VM test proves Firefox accepts ours.)

## Files

`/var/lib/survival-kit/tls/` — runtime state, never in the Nix store or the ISO: every box
makes its own keys.

| File | Mode | |
|---|---|---|
| `ca.key` | 0600 root | the CA's signing key — the sensitive one |
| `ca.crt` | 0644 | the CA certificate (public) |
| `deck.key` | 0640 root:nginx | the site key — nginx runs as user `nginx` and must read it |
| `deck.crt` | 0644 | the site certificate |

`web.nix` sets `forceSSL` and the certificate paths on every vhost; nginx `Requires` and
starts `After` the TLS service, so a re-issued certificate restarts nginx with it.

## On the command line

Command-line tools don't know the box's CA (it is deliberately not in the system trust
store), so pass it explicitly:

    curl --cacert /var/lib/survival-kit/tls/ca.crt https://wiki.deck/
    openssl x509 -in /var/lib/survival-kit/tls/deck.crt -noout -text   # inspect

## Starting over

`sudo rm -r /var/lib/survival-kit/tls && sudo reboot` — a new CA and certificate are made
at boot; Firefox picks up the new CA when it starts.

## Limits (hub mode, later)

- Opening the box by IP address (`https://192.168.…`) shows a warning: a certificate can't
  name an address that changes.
- Other devices will need `ca.crt` installed; publishing it comes with hub mode.
