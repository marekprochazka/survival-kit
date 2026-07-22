{ config, pkgs, lib, ... }:
{
  networking.networkmanager.enable = true;

  # mDNS so the box answers to <hostname>.local on any LAN:
  services.avahi = {
      enable = true;
      nssmdns4 = true; # resolve *.local via NSS
      publish = { enable = true; addresses = true; workstation = true; };
  };

  time.timeZone = "Europe/Berlin";
  i18n.defaultLocale = "en_US.UTF-8";
  console.keyMap = "us";

  # nix config on actual instance
  nix.settings.experimental-features = [ "nix-command" "flakes" ];
  nix.settings.auto-optimise-store = true;
  nix.gc = {  # keep the store from growing forever when instance does rebuilds
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 30d";
  };

  # security
  security.sudo.wheelNeedsPassword = true; 

  # base system packages
  environment.systemPackages = with pkgs; [
      vim git htop tmux curl
    ];
}