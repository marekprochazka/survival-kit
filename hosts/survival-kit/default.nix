{
  config,
  pkgs,
  lib,
  ...
}:
{
  # pull in the base system + disk layout
  imports = [
    ../../modules/base
    ./disko.nix
  ];

  networking.hostName = "survival-kit";

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
