# Profiles (ADR-0001/0002): which services a box gets, chosen once at install.
#   lite — for low RAM / a slow CPU: wiki, passwords
#   full — lite + the heavy services (≥ 8 GB RAM, i5-class): local AI
# Defaults only (mkDefault): a single service can still be switched on/off by hand.
# Add a new service here. Not profile-dependent: dashboard, desktop, first boot, TLS.
{ config, lib, ... }:
let
  inherit (config.survivalKit) profile;
in
{
  options.survivalKit.profile = lib.mkOption {
    type = lib.types.enum [
      "lite"
      "full"
    ];
    description = ''
      Which services this box gets. Chosen at install (written to selection.nix);
      switching later is not supported — reinstall from the ISO.
    '';
  };

  config.survivalKit.services = {
    kiwix.enable = lib.mkDefault true;
    vaultwarden.enable = lib.mkDefault true;
    content.enable = lib.mkDefault true; # the content manager (both profiles)
    ollama.enable = lib.mkDefault (profile == "full");
  };
}
