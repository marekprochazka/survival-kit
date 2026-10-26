# Layout

The repository (on an installed box: `/etc/nixos`):

| Path | What it is |
|---|---|
| `flake.nix` | Entry point: inputs (nixpkgs, disko) and outputs (two systems, packages, checks, formatter) |
| `flake.lock` | Exact pinned versions of the inputs — same lock, same system |
| `hosts/survival-kit/default.nix` | The installed system: which modules, the account, the bootloader |
| `hosts/survival-kit/disko.nix` | Disk layout (partitions, optional encryption) as options |
| `hosts/survival-kit/selection.nix` | *Only on installed boxes:* disk + encryption chosen at install |
| `hosts/survival-kit/hardware-detected.nix` | *Only on installed boxes:* detected hardware, reference only |
| `hosts/installer/default.nix` | The live installer ISO |
| `modules/base/` | Network, mDNS, locale, Nix settings, hardware drivers, git trust |
| `modules/services/web.nix` | The service **registry** and what it generates (nginx, hosts, health) |
| `modules/tls/` | HTTPS: the box's certificate authority and site certificate, made at boot |
| `modules/services/vaultwarden/` | Passwords: the Vaultwarden service |
| `modules/services/kiwix/` | The offline wiki: service, catalog rebuild, bundled books |
| `modules/dashboard/` | The dashboard page generator, its CSS and status script |
| `modules/desktop/` | XFCE, autologin, Firefox, XFCE defaults (`xfconf/`), dashboard autostart |
| `modules/firstboot/` | The first-start name/password prompt |
| `modules/installer/` | The `survival-kit-install` command + what an offline install needs |
| `pkgs/books.nix` | Builds the wiki books (manual, this guide) from Markdown |
| `pkgs/survival-kit-install.{nix,sh}` | The installer script |
| `manual/` | The user manual (Markdown) |
| `devguide/` | This guide (Markdown) |
| `checks/` | Tests — see [Testing](testing.html) |
| `.githooks/pre-commit` | Runs the lint check before each commit |
| `.github/workflows/ci.yml` | CI: lint + config checks on every push (when hosted on GitHub) |
| `README.md` | Short project overview |

Conventions:

- **One module per area**, a `default.nix` per directory. Modules are always imported
  (via the host's `imports`) and do nothing until their option is enabled — *import is not
  enable*.
- Shell logic lives in `.sh` files and is wrapped with `writeShellApplication`, which adds
  `set -euo pipefail`, puts the listed tools on `PATH`, and runs **shellcheck** at build time.
- Formatting: `nix fmt` (nixfmt). Lints: statix and deadnix (run by the `lint` check).
