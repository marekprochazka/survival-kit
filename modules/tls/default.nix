# HTTPS for the box (see devguide/tls.md): at every boot, before nginx, make sure
# the box's own certificate authority exists and the site certificate covers every
# name we serve (deck, each registered <sub>.deck, <hostname>.local). Keys are made
# on the box, live in /var/lib (never in the Nix store) and are root-only.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.tls;
  inherit (config.survivalKit.web) domain;
  inherit (config.networking) hostName;
  # every name the site certificate must carry — explicit, because a wildcard
  # *.deck doesn't match under a single-label name
  names = [
    domain
  ]
  ++ lib.mapAttrsToList (_: svc: "${svc.subdomain}.${domain}") config.survivalKit.registry
  ++ [ "${hostName}.local" ];
  # what the CA may ever vouch for (name constraints)
  permitted = [
    domain
    ".${domain}"
    "${hostName}.local"
  ];
  tlsScript = pkgs.writeShellApplication {
    name = "survival-kit-tls";
    runtimeInputs = with pkgs; [
      openssl
      coreutils
    ];
    text = ''
      TLS_DIR=${lib.escapeShellArg cfg.dir}
      CA_SUBJECT=${lib.escapeShellArg "survival-kit local CA (${hostName})"}
      PERMITTED=${lib.escapeShellArg (lib.concatStringsSep " " permitted)}
      NAMES=${lib.escapeShellArg (lib.concatStringsSep " " names)}
      KEY_GROUP=${lib.escapeShellArg (lib.optionalString config.services.nginx.enable config.services.nginx.group)}
    ''
    + builtins.readFile ./tls.sh;
  };
in
{
  options.survivalKit.tls = {
    enable = lib.mkEnableOption "HTTPS with a certificate authority made on the box" // {
      default = true;
    };
    dir = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/survival-kit/tls";
      readOnly = true;
      description = "Where ca.{key,crt} and deck.{key,crt} live (runtime state).";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.survival-kit-tls = {
      description = "survival-kit: certificate authority and site certificate";
      wantedBy = [ "multi-user.target" ];
      before = [ "nginx.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = lib.getExe tlsScript;
      };
    };
  };
}
