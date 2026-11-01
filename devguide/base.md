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
- **Memory — zram swap, no swap file:** `zramSwap` (zstd, `memoryPercent = 50`) gives a swap
  device in RAM (`/dev/zram0`) that compresses what's written to it (≈ 3:1). Rarely used
  pages get squeezed there instead of programs being killed, with no disk writes. 50 % is the
  most uncompressed data it may hold, not memory reserved up front. Check: `zramctl`,
  `swapon --show`. There's **deliberately no swap file**: on an old, slow disk a swapping box
  feels broken rather than slow. An owner with a fast SSD who wants one adds it in
  `/etc/nixos` (e.g. `swapDevices = [ { device = "/var/lib/swapfile"; size = 4096; } ];`,
  size in MB) and rebuilds.
- **sudo** for `wheel` with a password; a few base tools (vim, git, htop, tmux, curl).

What "offline" does **not** cover: rebuilding a *changed* configuration usually needs to
build new things, and the build tools are not on the box. See [Workflows](workflows.html).
