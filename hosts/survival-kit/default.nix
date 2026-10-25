{ ... }:
{
  # pull in the base system + disk layout
  imports = [
    ../../modules/base
    ../../modules/services
    ../../modules/dashboard
    ../../modules/desktop
    ./disko.nix
  ];

  networking.hostName = "survival-kit";

  # services (no lite/full profiles yet — ADR-0002 profiles come with ≥2 services)
  survivalKit.services.kiwix.enable = true;

  users.users.hera = {
    # as hera syndulla
    isNormalUser = true;
    extraGroups = [ "wheel" ]; # sudo rights
    initialPassword = "changeme";
  };

  survivalKit.desktop = {
    enable = true;
    autoLoginUser = "hera"; # dev user; replaced by first-boot user creation later
  };

  # dev VM (utils/run) only — XFCE + Firefox need more than the 1 GB default
  virtualisation.vmVariant.virtualisation.memorySize = 2048;

  # The release this system was first installed with. Keeps stateful services
  # compatible with their existing on-disk data. Never bump it on upgrades.
  system.stateVersion = "26.05";

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
}
