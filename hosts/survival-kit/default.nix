{ ... }:
{
  # pull in the base system + disk layout
  imports = [
    ../../modules/base
    ../../modules/services
    ../../modules/dashboard
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

  services.getty.autologinUser = "hera";

  # The release this system was first installed with. Keeps stateful services
  # compatible with their existing on-disk data. Never bump it on upgrades.
  system.stateVersion = "26.05";

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;
}
