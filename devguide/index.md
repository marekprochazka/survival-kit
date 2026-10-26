# survival-kit developer guide

This guide explains how survival-kit is built and how to change it — written so you can
work on it **without internet**. It assumes you know Linux and a shell. For the Nix language
and NixOS itself, see [Decisions & reference](decisions.html) for what's available offline
on this box.

## The big picture

survival-kit is a NixOS system described entirely by one **flake** (the source lives in
`/etc/nixos` on an installed box). From that flake come two systems:

- **`survival-kit`** — the system that runs on the machine: base settings, services (the
  offline wiki and the password manager; local AI on `full` boxes — see Profiles), the dashboard, the desktop, and the first-boot prompt.
- **`installer`** — a live ISO that installs `survival-kit` onto a disk, offline.

Everything is a NixOS **module**: a file that declares options and sets configuration.
survival-kit's own options all live under `survivalKit.*`, e.g.
`survivalKit.services.kiwix.enable`.

How a request from the browser reaches a service:

    Firefox → https://wiki.deck
      → /etc/hosts says wiki.deck = 127.0.0.1
      → nginx (port 443, the box's own certificate — see HTTPS)
      → vhost "wiki.deck" → 127.0.0.1:8080 (kiwix-serve)

The dashboard (`https://deck`) is a static page generated at build time from the list of
registered services; a small script checks each service through `https://deck/health/<name>`.

## How to read this guide

1. [Layout](layout.html) — what each file is for.
2. [Flake](flake.html) — how the two systems are assembled.
3. One page per area: [Base](base.html), [Services](services.html) (incl. **adding a
   service**), [Profiles](profiles.html), [HTTPS](tls.html), [Kiwix](kiwix.html),
   [Vaultwarden](vaultwarden.html), [Ollama](ollama.html), [Dashboard](dashboard.html), [Desktop](desktop.html),
   [First boot](firstboot.html), [Installer & ISO](installer.html).
4. [Testing](testing.html) and [Workflows](workflows.html) — changing things safely.
5. [Decisions & reference](decisions.html) — *why* it is built this way.
