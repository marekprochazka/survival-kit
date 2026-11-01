# Inventory — Homebox, a household inventory (what, where, how much) at https://inventory.<domain>.
# Built on nixpkgs' services.homebox (own user, confined unit, SQLite + attachment files in
# /var/lib/homebox/data — on this device, not on added drives). Sharing uses Homebox's own
# collections: the manual suggests one shared "Household" collection joined by invitation.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.services.inventory;
  port = 7745;
  url = "https://inventory.${config.survivalKit.web.domain}";
  dataDir = "/var/lib/homebox/data"; # homebox.db + one attachment folder per collection
  backupRoot = "/var/backup/homebox";
  # Nightly copy: latest/ = consistent database + mirrored attachments; daily/<date> = hard
  # links to latest/, so 7 days cost about one copy of the photos. Rule: nothing in latest/
  # is ever changed in place (it is shared with the dated copies) — the database is written
  # to a new file and moved over, rsync replaces changed files by rename (no --inplace).
  backup = pkgs.writeShellApplication {
    name = "homebox-backup";
    runtimeInputs = with pkgs; [
      coreutils
      findutils
      rsync
      sqlite
    ];
    text = ''
      if [ ! -f ${dataDir}/homebox.db ]; then
        echo "no inventory database yet (Homebox has never started) — nothing to back up"
        exit 0
      fi
      install -d -m 0700 ${backupRoot} ${backupRoot}/latest ${backupRoot}/daily
      cd ${backupRoot}
      # database first: a photo without its record is harmless, a record without its photo isn't
      rm -f latest/homebox.db.tmp
      # wait up to 10 s if Homebox holds a lock (e.g. starting up) instead of skipping the night
      sqlite3 -cmd '.timeout 10000' ${dataDir}/homebox.db ".backup 'latest/homebox.db.tmp'"
      # the copy inherits WAL mode; switch it off so opening a copy never creates -wal/-shm
      # files beside it (Homebox turns WAL back on itself after a restore)
      sqlite3 latest/homebox.db.tmp "PRAGMA journal_mode=DELETE" >/dev/null
      mv -f latest/homebox.db.tmp latest/homebox.db
      rsync -a --delete --exclude 'homebox.db*' ${dataDir}/ latest/
      day=$(date +%F)
      # build under a temporary name, rename when complete: an interrupted copy (disk full)
      # never looks like a real day, never counts toward the 7, can't be restored by mistake
      rm -rf daily/.*.tmp
      cp -al latest "daily/.$day.tmp"
      rm -rf "daily/$day"
      mv "daily/.$day.tmp" "daily/$day"
      touch "daily/$day"
      # keep the newest 7 by age, not by name (a wrong clock must not make the newest look oldest)
      # shellcheck disable=SC2012 # names are dates (no spaces/newlines)
      ls -1dt daily/* | tail -n +8 | xargs -r rm -rf
    '';
  };
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

    # same disk: guards against mistakes and a damaged database (noticed within a week),
    # not against a dead disk. Timer only — a run at boot would overwrite a good copy.
    systemd.services.backup-homebox = {
      description = "Back up the inventory (Homebox)";
      after = [ "homebox.service" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = lib.getExe backup; # as root: Homebox's files are 0600 homebox
        # often runs at boot (Persistent, box off at 23:00) next to the desktop: stay out of the way
        Nice = 19;
        IOSchedulingClass = "idle";
      };
    };
    systemd.timers.backup-homebox = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = "23:00";
        Persistent = true; # missed (box off) → at the next boot
      };
    };

    # nginx's default body limit is 1 MB; match Homebox's (upload limit + 1 MB form overhead)
    services.nginx.virtualHosts."inventory.${config.survivalKit.web.domain}".extraConfig = ''
      client_max_body_size 33m;
    '';
  };
}
