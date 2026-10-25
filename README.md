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
  encryption.
- First start asks for your name and a password; then the XFCE desktop logs in
  automatically and Firefox opens the dashboard.
- Dashboard at `http://deck`, with a live status dot per service.
- Offline wiki (Kiwix) at `http://wiki.deck` with the Arch Wiki, man pages, Nix/bash/git
  docs and a built-in user manual.

Not yet: more services (password manager, file sync, offline maps, local LLM, …),
light/full profiles, importing content from USB drives, Wi-Fi hotspot mode, updates.

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
| `modules/` | base system, services (web registry, Kiwix), dashboard, desktop, first boot, installer |
| `pkgs/` | the installer script, the manual builder |
| `manual/` | end-user manual (shipped as a book in the offline wiki) |
| `checks/` | tests (lint, config checks, VM tests) |
| `.githooks/` | pre-commit lint — enable with `git config core.hooksPath .githooks` |

## Status

Personal project, work in progress.
