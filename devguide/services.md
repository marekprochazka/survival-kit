# Services

## The registry

Every web service registers **one entry** in `survivalKit.registry.<name>`. From the whole
registry, `modules/services/web.nix` generates everything else, so nothing can drift apart:

| Generated | From |
|---|---|
| nginx vhost `<subdomain>.<domain>` → `http://127.0.0.1:<port>` | each entry |
| `/etc/hosts`: `127.0.0.1 deck <subdomain>.deck …` | each entry |
| `http://deck/health/<name>` → the service's `healthPath` | each entry |
| a dashboard tile | each entry (see [Dashboard](dashboard.html)) |

Registry entry fields: `subdomain` (default: the name), `port` (required), `title`,
`description`, `order` (dashboard position, default 100), `healthPath` (default `/`).
The domain is `survivalKit.web.domain` (default `deck`).

**Build-time checks** (NixOS `assertions` in `web.nix`): the build fails with a clear
message if two entries share a subdomain or a port, or a subdomain is empty or equals the
bare domain.

nginx itself always runs (the dashboard is always there). The `deck` vhost is the
**default** one, so opening the box by IP or `<hostname>.local` shows the dashboard. Port 80
is closed to other machines by the firewall (opening it is future "hub mode" work).

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
3. Enable it in `hosts/survival-kit/default.nix`:
   `survivalKit.services.notes.enable = true;`
4. Rebuild. You get `http://notes.deck`, a hosts entry, a health endpoint and a dashboard
   tile — without touching `web.nix` or the dashboard.
5. Add a test: a subtest in `checks/services.nix` (or a new VM test) that the service
   answers at `http://notes.deck` — see [Testing](testing.html).

Find the NixOS service options with `man configuration.nix` (search `/services.notes`) or
`nixos-option services.<name>`.
