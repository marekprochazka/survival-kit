# Decisions & reference

## Why it is built this way

- **NixOS + one flake:** the whole system — disk layout, services, desktop, installer — is
  declared in one place and reproducible; the same flake gives the installed system, the
  dev VM, the tests and the ISO.
- **Offline first:** every feature must work without a network. That decided many details:
  services on `127.0.0.1` + nginx, the ISO carrying the prebuilt system, input sources kept
  on the box, Firefox telemetry and online extras switched off.
- **Install to disk** (not a live USB system): the box is persistent and owned by its user.
- **Installer = script, not GUI:** `disko` (declarative partitions) + `nixos-install`,
  wrapped in a short guided script.
- **Hybrid BIOS + UEFI with GRUB:** old hardware is often BIOS-only.
- **All-hardware drivers instead of per-machine detection:** a machine-specific config would
  have to be built on the target — impossible offline.
- **Fixed account `deck`, name + password at first start:** the person installing need not
  know the user's password; autologin needs a fixed name.
- **XFCE on X11:** light, familiar, works on old GPUs; Firefox opens the dashboard.
- **Service registry:** one entry per service generates nginx, hosts, health and the
  dashboard — nothing to keep in sync by hand.
- **Kiwix with a runtime catalog:** new wiki content without rebuilding.
- **Tests as flake checks** in layers: fast ones in CI, VM tests locally, installs by hand.

Planned but not built yet: more services (password manager, file sync, maps, local LLM …)
and light/full profiles, importing content from USB drives, a Wi-Fi hotspot ("hub") mode,
updates, an offline build kit, themes.

## Reference available offline on this box

- **NixOS manual:** run `nixos-help` (opens it in the browser).
- **Every NixOS option:** `man configuration.nix` (search with `/`), or
  `nixos-option <option>` for the current value.
- **Nix language builtins:** [Nix docs in the wiki](https://wiki.deck/content/devdocs_en_nix/index).
- **nixpkgs `lib` functions** (`mkIf`, `mapAttrs`, …):
  [nixpkgs lib docs](https://wiki.deck/content/devdocs_en_nix/nixpkgs/stable/index).
- **Linux in general:** the Arch Wiki and man pages books in the wiki.
- **This system:** read the code — every module starts with a comment saying what it does.
