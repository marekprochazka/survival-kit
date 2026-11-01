# Vaultwarden — offline password manager (Bitwarden-compatible) at https://vault.<domain>.
# The Bitwarden web vault needs a secure context → HTTPS (modules/tls) is a prerequisite.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.services.vaultwarden;
  port = 8222;
  backupRoot = "/var/backup/vaultwarden";
  # after each backup: keep a dated copy of latest/, the newest 7 (by age, not by
  # name — a wrong clock must not make the newest copy look oldest)
  keepDaily = pkgs.writeShellApplication {
    name = "vaultwarden-keep-daily";
    runtimeInputs = with pkgs; [
      coreutils
      findutils
    ];
    text = ''
      cd ${backupRoot}
      day=$(date +%F)
      mkdir -p daily
      # build under a temporary name, rename when complete: an interrupted copy (disk full)
      # never looks like a real day, never counts toward the 7, can't be restored by mistake
      rm -rf daily/.*.tmp
      cp -a latest "daily/.$day.tmp"
      rm -rf "daily/$day"
      mv "daily/.$day.tmp" "daily/$day"
      touch "daily/$day"
      # shellcheck disable=SC2012 # names are dates (no spaces/newlines)
      ls -1dt daily/* | tail -n +8 | xargs -r rm -rf
    '';
  };
in
{
  options.survivalKit.services.vaultwarden.enable =
    lib.mkEnableOption "Vaultwarden offline password manager";

  config = lib.mkIf cfg.enable {
    services.vaultwarden = {
      enable = true;
      # upstream writes one copy of the database + keys here; keepDaily (below) keeps
      # 7 dated copies. Same disk: guards against mistakes and a damaged database
      # (noticed within a week), not against a dead disk.
      backupDir = "${backupRoot}/latest";
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
    systemd.services.backup-vaultwarden = {
      # timer only (23:00; Persistent → at the next boot if the box was off). Upstream
      # also runs it at every boot, which would overwrite a good copy before anyone
      # noticed a problem.
      wantedBy = lib.mkForce [ ];
      serviceConfig = {
        ExecStartPost = "+${lib.getExe keepDaily}"; # "+": as root
        # often runs at boot (Persistent, box off at 23:00) next to the desktop: stay out of the way
        Nice = 19;
        IOSchedulingClass = "idle";
      };
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
