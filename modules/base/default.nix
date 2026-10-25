{ pkgs, inputs, ... }:
{
  networking.networkmanager.enable = true;

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
