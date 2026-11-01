{ pkgs, inputs, ... }:
{
  networking.networkmanager.enable = true;

  # Swap in RAM, compressed (zstd ≈ 3:1): rarely used pages are squeezed instead of the box
  # running out of memory (Firefox + wiki on 4 GB, a 3B model on 8 GB). 50 % = the most
  # uncompressed data it may hold, nothing is reserved up front. No swap file on disk
  # (decided): on old disks it makes a low-spec box feel broken rather than slow.
  zramSwap = {
    enable = true;
    algorithm = "zstd";
    memoryPercent = 50;
  };

  # Heavy background work (Ollama answering, Jellyfin scanning) gives way to the desktop.
  # CPU weight only splits CPU among siblings, so it gets its own top-level slice next to
  # system.slice (100) and user.slice (100, the desktop): 100 : 100 : 20 → the desktop
  # keeps ~83 % under load; an otherwise idle box still gives the work every core.
  systemd.slices.background = {
    description = "Heavy background work that gives way to the desktop";
    sliceConfig.CPUWeight = 20;
  };

  # mDNS so the box answers to <hostname>.local on any LAN:
  services.avahi = {
    enable = true;
    nssmdns4 = true; # resolve *.local via NSS
    publish = {
      enable = true;
      addresses = true;
      workstation = true;
    };
  };

  time.timeZone = "Europe/Berlin";
  i18n.defaultLocale = "en_US.UTF-8";
  console.keyMap = "us";

  # nix config on actual instance
  nix = {
    settings = {
      experimental-features = [
        "nix-command"
        "flakes"
      ];
      auto-optimise-store = true;
    };
    gc = {
      # keep the store from growing forever when instance does rebuilds
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 30d";
    };
    # pinned nixpkgs for `nix shell nixpkgs#…` — works offline (source is on the system)
    registry.nixpkgs.flake = inputs.nixpkgs;
  };

  # Offline rebuilds of /etc/nixos: keep this flake's input sources on the system.
  system.extraDependencies = map (input: input.outPath) [
    inputs.nixpkgs
    inputs.disko
  ];

  # Same broad driver set as the installer ISO: whatever boots the ISO boots the
  # install, and every install is the identical prebuilt system (offline install).
  # The machine's detected config is kept for reference in hardware-detected.nix.
  hardware = {
    enableAllHardware = true;
    enableRedistributableFirmware = true;
  };

  # /etc/nixos is a root-owned git repo (made by the installer); let users read
  # it (`git -C /etc/nixos log`) without git's "dubious ownership" refusal
  programs.git = {
    enable = true;
    config.safe.directory = "/etc/nixos";
  };

  # security
  security.sudo.wheelNeedsPassword = true;

  # base system packages
  environment.systemPackages = with pkgs; [
    vim
    git
    htop
    tmux
    curl
  ];
}
