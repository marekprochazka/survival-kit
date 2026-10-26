# Services

## The registry

Every web service registers **one entry** in `survivalKit.registry.<name>`. From the whole
registry, `modules/services/web.nix` generates everything else, so nothing can drift apart:

| Generated | From |
|---|---|
| nginx vhost `https://<subdomain>.<domain>` → `http://127.0.0.1:<port>` (http → 301, WebSockets passed through) | each entry |
| `/etc/hosts`: `127.0.0.1 deck <subdomain>.deck …` | each entry |
| `https://deck/health/<name>` → the service's `healthPath` | each entry |
| the name `<subdomain>.deck` in the site certificate (see [HTTPS](tls.html)) | each entry |
| a dashboard tile | each entry (see [Dashboard](dashboard.html)) |

Registry entry fields: `subdomain` (default: the name), `port` (required), `title`,
`description`, `order` (dashboard position, default 100), `healthPath` (default `/`).
The domain is `survivalKit.web.domain` (default `deck`).

**Build-time checks** (NixOS `assertions` in `web.nix`): the build fails, naming the
entries involved, if two entries share a subdomain (case-insensitive) or a port, an entry
uses port 80/443 (nginx's own), a name or subdomain uses anything but `a-z`, `0-9` and
`-`, or a subdomain equals the bare domain.

nginx itself always runs (the dashboard is always there). The `deck` vhost is the
**default** one, so opening the box by IP or `<hostname>.local` shows the dashboard. Ports 80
and 443 are closed to other machines by the firewall (opening it is future "hub mode" work).

## Adding a service — step by step

Example: a service `notes` that listens on port 3000.

1. Create `modules/services/notes/default.nix`:

        { config, lib, ... }:
        let
          cfg = config.survivalKit.services.notes;
        in
        {
          options.survivalKit.services.notes.enable = lib.mkEnableOption "notes";

          config = lib.mkIf cfg.enable {
            # the actual NixOS service — listen on 127.0.0.1 only
            services.<the-nixos-service> = { enable = true; /* … port 3000 … */ };

            survivalKit.registry.notes = {
              port = 3000;
              title = "Notes";
              description = "Offline notes";
              order = 40;
            };
          };
        }

2. Add `./notes` to the `imports` in `modules/services/default.nix`.
3. Put it in a profile, in `modules/profiles/default.nix`:
   `notes.enable = lib.mkDefault true;` (or `lib.mkDefault (profile == "full")` for a
   heavy one) — see [Profiles](profiles.html).
4. Rebuild. You get `https://notes.deck` (with the name added to the certificate), a hosts
   entry, a health endpoint and a dashboard tile — without touching `web.nix` or the dashboard.
5. Add a test: a subtest in `checks/services.nix` (or a new VM test) that the service
   answers at `https://notes.deck` (with `curl --cacert …/ca.crt`) — see [Testing](testing.html).

**Content from sticks.** If the service has content people bring on external media (books,
models, media), give it a kind in the [Content manager](content.html) rather than its own
import path.

**Email-shaped logins.** If a service insists on an email address as the login name, the
box's convention is `<name>@<subdomain>.deck` (e.g. `anna@vault.deck`) — nothing is ever
mailed. Say so on the service's manual page.

Find the NixOS service options with `man configuration.nix` (search `/services.notes`) or
`nixos-option services.<name>`.
