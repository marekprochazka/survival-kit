# Files (ADR-0006 amendment) at https://files.<domain>: File Browser as a small personal cloud.
# Anyone signs up (<name>@files.<domain>, like Passwords) and gets a space: one folder per
# location — this device and each connected added drive — kept at <location>/files/<account>/,
# plus Library/ with the box's wiki books and maps, read-only (download, not change).
# A root service builds each space from bind mounts (../content/app/files_view.py); File
# Browser runs confined and never sees the content tree itself.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.services.files;
  storage = config.survivalKit.storage;
  kiwix = config.survivalKit.services.kiwix;
  maps = config.survivalKit.services.maps;
  fb = config.services.filebrowser;
  port = 8330;
  inherit (cfg) viewDir;
  db = fb.settings.database;
  # File Browser keeps its settings in its database: set them on every start. Made this
  # way the database has no users at all — File Browser's quick setup (an admin account
  # with a printed password) never runs.
  flags = lib.escapeShellArgs [
    "--auth.method=json"
    "--signup"
    "--createUserDir" # sign-up makes users/<account>/
    "--minimumPasswordLength=12"
    # what every new account may do: its own files, nothing more
    "--perm.admin=false"
    "--perm.share=false" # no public links
    "--perm.execute=false"
    "--perm.create"
    "--perm.rename"
    "--perm.modify"
    "--perm.delete"
    "--perm.download"
    "--hideDotfiles"
    "--disableExec" # no command runner
    "--branding.name=Files"
    "--branding.disableExternal" # no links to github.com on an offline box
    "--branding.disableUsedPercentage"
    "--root=${viewDir}"
  ];
  tool = pkgs.writeShellApplication {
    name = "survival-kit-files";
    runtimeInputs = [
      fb.package
      pkgs.util-linux # runuser
      config.systemd.package # systemctl
    ];
    text = ''
      usage() {
        echo "usage: sudo survival-kit-files reset-password <name>   (e.g. anna@files.${config.survivalKit.web.domain})" >&2
        exit 2
      }
      [ "''${1:-}" = reset-password ] && [ $# -eq 2 ] || usage
      [ "$(id -u)" -eq 0 ] || { echo "survival-kit-files: run it with sudo" >&2; exit 1; }
      name=$2
      read -rsp "New password for $name: " pw; echo >&2
      read -rsp "Once more: " again; echo >&2
      [ "$pw" = "$again" ] || { echo "survival-kit-files: the two passwords differ" >&2; exit 1; }
      [ ''${#pw} -ge 12 ] || { echo "survival-kit-files: at least 12 characters" >&2; exit 1; }
      # File Browser locks its database while it runs: stop it, always start it again
      systemctl stop filebrowser.service
      trap 'systemctl start filebrowser.service' EXIT
      runuser -u ${fb.user} -- filebrowser -d ${db} users update "$name" --password "$pw"
      echo "survival-kit-files: the password of $name is changed" >&2
    '';
  };
in
{
  options.survivalKit.services.files = {
    enable = lib.mkEnableOption "Files (File Browser: a personal cloud + the box's books and maps)";
    viewDir = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/survival-kit-files/view";
      readOnly = true;
      description = "What File Browser shows: users/<account>/ = each person's space (bind mounts).";
    };
  };

  config = lib.mkIf cfg.enable {
    services.filebrowser = {
      enable = true;
      # sign-up: one account, one home folder (File Browser would put "a..b" and "ab" in one)
      package = pkgs.filebrowser.overrideAttrs (old: {
        patches = (old.patches or [ ]) ++ [ ./signup.patch ];
      });
      settings = {
        address = "127.0.0.1"; # only nginx talks to it
        inherit port;
        root = viewDir;
      };
    };

    # exFAT/NTFS drives have no owners: mount them writable for File Browser's group
    survivalKit.storage.filesGroup = fb.group;
    # the binds of a drive's folders into the spaces are the box's own, not "the drive is in use"
    systemd.services.survival-kit-drives.environment.OURS = "${viewDir}/";

    systemd = {
      services.filebrowser = {
        wants = [ "survival-kit-files-view.service" ];
        after = [ "survival-kit-files-view.service" ];
        preStart = ''
          if [ -e ${db} ]; then
            ${lib.getExe fb.package} -d ${db} config set ${flags}
          else
            ${lib.getExe fb.package} -d ${db} config init ${flags}
          fi
        '';
        serviceConfig = {
          # the spaces are bind mounts of folders in the content tree; File Browser itself
          # can't reach the tree (nor anything else it isn't given)
          InaccessiblePaths = [ "/var/lib/survival-kit" ];
          ProtectSystem = "strict";
          ReadWritePaths = [
            viewDir
            (dirOf db)
          ];
          ProtectHome = true;
          PrivateTmp = true;
        };
      };

      # the spaces: run at boot, after a sign-up and after every drive change (path unit)
      services.survival-kit-files-view = {
        description = "Build each person's space in Files";
        wantedBy = [ "multi-user.target" ];
        after = [ "survival-kit-drives.service" ];
        before = [ "filebrowser.service" ];
        startLimitIntervalSec = 0;
        path = [ pkgs.util-linux ]; # mount, umount
        environment = {
          DATA_DIR = storage.dataDir;
          DRIVES_DIR = storage.drivesDir;
          REGISTRY = storage.registryFile;
          DRIVE_STATE = storage.driveStateFile;
          VIEW_DIR = viewDir;
          # kept across reboots: the next boot takes down folders of drives that are gone
          VIEW_STATE = "/var/lib/survival-kit-files/view.json";
          BUILTIN_WIKI = lib.optionalString (kiwix.starterDir != null) "${kiwix.starterDir}";
          BUILTIN_MAPS = lib.optionalString maps.enable "${maps.builtinDir}";
          OWNER = fb.user;
          PYTHONUNBUFFERED = "1";
        };
        # not sandboxed: its mounts must be seen by File Browser (no RemainAfterExit, so the
        # path unit can start it again)
        serviceConfig = {
          Type = "oneshot";
          ExecStart = "${pkgs.python3}/bin/python3 ${../content/app}/files_view.py";
        };
      };

      paths.survival-kit-files-view = {
        wantedBy = [ "multi-user.target" ];
        pathConfig.PathChanged = [
          "${viewDir}/users" # File Browser made a new account's folder
          storage.driveStateFile # a drive was added, forgotten, pulled out or plugged back
        ];
      };

      # the view root and the space folders are root's (people can't drop files at the top);
      # File Browser makes users/<account>/ at sign-up
      tmpfiles.settings.filebrowser.${viewDir}.d = lib.mkForce {
        user = "root";
        group = "root";
        mode = "0755";
      };
      tmpfiles.rules = [ "d ${viewDir}/users 0755 ${fb.user} ${fb.group} -" ];
    };

    environment.systemPackages = [ tool ];

    survivalKit.registry.files = {
      subdomain = "files";
      inherit port;
      title = "Files";
      description = "Your own files, and the box's books and maps to download";
      order = 16; # after Passwords (15)
      healthPath = "/health";
    };

    # uploads of any size, streamed to File Browser instead of buffered by nginx
    services.nginx.virtualHosts."files.${config.survivalKit.web.domain}".extraConfig = ''
      client_max_body_size 0;
      proxy_request_buffering off;
      proxy_read_timeout 3600s;
      proxy_send_timeout 3600s;
    '';
  };
}
