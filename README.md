# survival-kit

An offline-first "computer in a box" built on NixOS. Install it on an old laptop or a
homemade cyberdeck and you get a desktop, an offline wiki and a dashboard — no internet
needed.

## Goals

- **Offline first** — everything works without a network.
- **Low-spec hardware** — old notebooks, little RAM, no GPU.
- **Zero-touch** — install, answer two questions at first start, land on the dashboard.
- **Declarative** — this flake is the whole system; the installer ISO is built from it.

## Current state

Working prototype, tested in QEMU and VirtualBox (not yet on real hardware).

- Installer ISO: boots via BIOS, UEFI and USB, installs **offline**, optional disk
  encryption, profile **lite** (low-spec machines) or **full** (adds local AI).
- First start asks for your name and a password; then the XFCE desktop logs in
  automatically and Firefox opens the dashboard.
- Everything over HTTPS with a certificate authority made on the box (Firefox trusts it).
- Dashboard at `https://deck`, with a live status dot per service.
- Offline wiki (Kiwix) at `https://wiki.deck` with the Arch Wiki, man pages, Nix/bash/git
  docs and a built-in user manual.
- Password manager (Vaultwarden) at `https://vault.deck`.
- `full` only: local AI models (Ollama, CPU) in the terminal; models come from a USB stick.

Not yet: more services (file sync, offline maps, notes, media, …), importing content from
USB drives, a chat page for the AI, Wi-Fi hotspot mode, updates.

## Try it

Needs Nix with flakes on x86_64 Linux (KVM for the VMs and tests).

```sh
# installer ISO (~3 GB) → result/iso/
nix build .#iso

# quick VM of the installed system, without installing
nix build .#nixosConfigurations.survival-kit.config.system.build.vm
./result/bin/run-survival-kit-vm

# all tests (VM tests need KVM)
nix flake check
```

Installing: boot the ISO and the installer starts by itself. It erases the disk you pick
(you type its name to confirm). When it says "Done": shut down, remove the install
medium, switch on again.

## Layout

| Path | What |
|---|---|
| `flake.nix` | the two systems: `survival-kit` (installed) and `installer` (ISO) |
| `hosts/` | per-system settings |
| `modules/` | base system, profiles, services (web registry, Kiwix, Vaultwarden, Ollama), HTTPS, dashboard, desktop, first boot, installer |
| `pkgs/` | the installer script, the wiki book builder |
| `manual/` | end-user manual (shipped as a book in the offline wiki) |
| `devguide/` | developer guide — how everything works and how to change it (also a wiki book) |
| `checks/` | tests (lint, config checks, VM tests) |
| `.githooks/` | pre-commit lint — enable with `git config core.hooksPath .githooks` |

## Status

Personal project, work in progress.
