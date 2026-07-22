{config, pkgs, lib,...}:
{

  imports = [ ../../modules/base ];  # pull in the base system

  networking.hostName = "survival-kit";

  users.users.hera = { # as hera syndulla
    isNormalUser = true;
    extraGroups = ["wheel"]; # sudo rights
    initialPassword = "changeme";
  };

  services.getty.autologinUser = "hera";

  # this must match version from root flake
  system.stateVersion = "26.05";
}