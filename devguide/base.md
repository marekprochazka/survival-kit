# Base

`modules/base/default.nix` — settings every survival-kit system has. Unlike the other
modules it has no `enable` option: importing it applies it.

- **Network:** NetworkManager (`nmtui`/`nmcli` for Wi-Fi). Nothing depends on a network;
  services listen on `127.0.0.1` only and the firewall keeps the NixOS default (incoming
  blocked).
- **mDNS:** avahi publishes the box as `<hostname>.local` on any LAN.
- **Locale:** `Europe/Berlin`, `en_US.UTF-8`, `us` keymap (fixed for now).
- **Nix on the box:** flakes enabled, store de-duplication (`auto-optimise-store`), weekly
  garbage collection of generations older than 30 days (offline; never deletes the running
  system).
- **Hardware:** `hardware.enableAllHardware` (the same broad driver set as the installer ISO
  — whatever boots the ISO boots the install) and `enableRedistributableFirmware` (Wi-Fi,
  Bluetooth, GPUs; ~800 MB).
- **Offline evaluation:** `system.extraDependencies` keeps the sources of the flake inputs
  (nixpkgs, disko) on the system, and `nix.registry.nixpkgs` pins `nixpkgs` to them — so
  `/etc/nixos` evaluates offline and `nix shell nixpkgs#<pkg>` works for packages already
  in the store.
- **git:** `safe.directory = "/etc/nixos"`, so users can read the root-owned repo.
- **sudo** for `wheel` with a password; a few base tools (vim, git, htop, tmux, curl).

What "offline" does **not** cover: rebuilding a *changed* configuration usually needs to
build new things, and the build tools are not on the box. See [Workflows](workflows.html).
