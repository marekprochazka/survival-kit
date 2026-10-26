# Vaultwarden — offline password manager (Bitwarden-compatible) at https://vault.<domain>.
# The Bitwarden web vault needs a secure context → HTTPS (modules/tls) is a prerequisite.
{ config, lib, ... }:
let
  cfg = config.survivalKit.services.vaultwarden;
  port = 8222;
in
{
  options.survivalKit.services.vaultwarden.enable =
    lib.mkEnableOption "Vaultwarden offline password manager";

  config = lib.mkIf cfg.enable {
    services.vaultwarden = {
      enable = true;
      # daily copy of the database + keys (23:00; Persistent → at next boot if the
      # box was off). Same disk: guards against a corrupted database, not a dead disk.
      backupDir = "/var/backup/vaultwarden";
      config = {
        ROCKET_ADDRESS = "127.0.0.1"; # only nginx talks to it
        ROCKET_PORT = port;
        DOMAIN = "https://vault.${config.survivalKit.web.domain}"; # links in the web vault
        SIGNUPS_ALLOWED = true; # anyone at the box can create an account (decided)
      };
    };
    # upstream orders it after network-online: pointless for a loopback-only service
    # on an offline box, and it would tie the password manager to the network coming up
    systemd.services.vaultwarden = {
      wants = lib.mkForce [ ];
      after = lib.mkForce [ ];
    };

    survivalKit.registry.vault = {
      subdomain = "vault";
      inherit port;
      title = "Passwords";
      description = "Offline password manager";
      order = 15; # between Wiki (10) and Manual (20)
      healthPath = "/alive";
    };
  };
}
