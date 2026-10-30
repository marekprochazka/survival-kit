# Content storage (ADR-0006): one content tree on several locations — this device and
# added drives — and the library, one merged and checked view of it that the services read:
# /var/lib/survival-kit/library/{wiki,maps}/ = links to the copy in use of every book and map.
# The logic is the content manager's Python (../content/app: locations.py, library.py).
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.storage;
  app = ./content/app;
  constant =
    value: description:
    lib.mkOption {
      type = lib.types.str;
      default = value;
      readOnly = true;
      inherit description;
    };
in
{
  options.survivalKit.storage = {
    dataDir = constant "/var/lib/survival-kit/data" "This device's content tree.";
    drivesDir = constant "/var/lib/survival-kit/drives" "Added drives are mounted at <drivesDir>/<uuid>.";
    libraryDir = constant "/var/lib/survival-kit/library" "The merged index (a symlink, swapped atomically).";
    registryFile = constant "/var/lib/survival-kit/drives.json" "The added drives (runtime data, no rebuild).";
    stateFile = constant "/var/lib/survival-kit/library.json" "What is in use / duplicate / invalid, for the content manager.";
    driveStateFile = constant "/run/survival-kit/drives.json" "Which added drives are mounted right now.";
    cacheFile = constant "/var/lib/survival-kit/content/checks.json" "Remembered check results.";
  };

  config = {
    systemd.tmpfiles.rules = [
      "d ${cfg.dataDir} 0755 root root -"
      "d ${cfg.drivesDir} 0755 root root -"
      "d ${dirOf cfg.cacheFile} 0755 root root -"
    ];

    systemd.services.survival-kit-library = {
      description = "Rebuild the content library from this device and the added drives";
      wantedBy = [ "multi-user.target" ];
      # drives first (mounted by survival-kit-drives), then the index, then the wiki's catalog
      wants = [ "survival-kit-drives.service" ];
      after = [ "survival-kit-drives.service" ];
      before = [ "kiwix-library.service" ];
      # re-run after every import/delete (content manager): no start limit
      startLimitIntervalSec = 0;
      path = [
        pkgs.kiwix-tools # kiwix-manage: can Kiwix read a book on a drive?
        config.systemd.package
      ];
      environment = {
        DATA_DIR = cfg.dataDir;
        DRIVES_DIR = cfg.drivesDir;
        REGISTRY = cfg.registryFile;
        DRIVE_STATE = cfg.driveStateFile;
        LIBRARY_DIR = cfg.libraryDir;
        STATE_FILE = cfg.stateFile;
        CACHE_FILE = cfg.cacheFile;
        PROTECTED = "survival-kit survival-kit-dev"; # the box's own manuals
        MAP_SCHEME = "4"; # Protomaps basemap version the bundled map style draws
        PYTHONUNBUFFERED = "1";
      };
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        ExecStart = "${pkgs.python3}/bin/python3 ${app}/library.py";
        # root (makes files on drives readable, swaps the index) — but confined
        ProtectSystem = "strict";
        ReadWritePaths = [ "/var/lib/survival-kit" ]; # incl. the drives mounted below it
        ProtectHome = true;
        PrivateTmp = true;
        NoNewPrivileges = true;
      };
    };
  };
}
