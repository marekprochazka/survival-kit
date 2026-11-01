# Inventory — Homebox, a household inventory (what, where, how much) at https://inventory.<domain>.
# Built on nixpkgs' services.homebox (own user, confined unit, SQLite + attachment files in
# /var/lib/homebox/data — on this device, not on added drives). Sharing uses Homebox's own
# collections: the manual suggests one shared "Household" collection joined by invitation.
{ config, lib, ... }:
let
  cfg = config.survivalKit.services.inventory;
  port = 7745;
  url = "https://inventory.${config.survivalKit.web.domain}";
in
{
  options.survivalKit.services.inventory.enable = lib.mkEnableOption "Homebox household inventory";

  config = lib.mkIf cfg.enable {
    services.homebox = {
      enable = true;
      settings = {
        HBOX_WEB_HOST = "127.0.0.1"; # only nginx talks to it
        HBOX_WEB_PORT = toString port;
        HBOX_WEB_MAX_UPLOAD_SIZE = "32"; # MB — phone photos (upstream default 10)
        HBOX_OPTIONS_ALLOW_REGISTRATION = "true"; # anyone at the box can sign up (decided)
        # the name Homebox 0.25 reads; upstream's module sets HBOX_OPTIONS_CHECK_GITHUB_RELEASE,
        # which Homebox ignores — without this it would try to reach GitHub
        HBOX_OPTIONS_GITHUB_RELEASE_CHECK = "false";
        # behind nginx (Homebox docs: required): take scheme and client address from its
        # forwarded headers — safe, Homebox listens on loopback only
        HBOX_OPTIONS_TRUST_PROXY = "true";
        HBOX_OPTIONS_HOSTNAME = url; # absolute links, e.g. invitations
      };
    };

    survivalKit.registry.inventory = {
      subdomain = "inventory";
      inherit port;
      title = "Inventory";
      description = "What we have and where";
      order = 17; # after Files (16)
      healthPath = "/api/v1/status";
    };

    # nginx's default body limit is 1 MB; match Homebox's upload limit
    services.nginx.virtualHosts."inventory.${config.survivalKit.web.domain}".extraConfig = ''
      client_max_body_size 32m;
    '';
  };
}
