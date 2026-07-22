{config, pkgs, lib,...}:
{
  networking.hostName = "survival-kit";

  users.users.hera = { # as hera syndulla
    isNormalUser = true;
    extraGroups = ["wheel"]; # sudo rights
    initialPassword = "changeme";
  };

  services.getty.autologinUser = "hera";

  # add other stuff we might want at a console
  environment.systemPackages = with pkgs; [ vim git ]; 

  # this must match version from root flake
  system.stateVersion = "26.05";
}