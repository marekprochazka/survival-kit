# Kiwix — offline wikis/docs (ZIM files) at http://wiki.<domain>.
# Catalog is runtime state: kiwix-library rebuilds library.xml at every boot
# from the drop-in dir, so new ZIMs need no rebuild (ADR-0004 fills zims/).
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.services.kiwix;
  dataDir = "/var/lib/survival-kit/kiwix";
  port = 8080;
  books = pkgs.callPackage ../../../pkgs/books.nix { };
  starterZims = import ./zims.nix { inherit pkgs; } // {
    survival-kit = books.manual;
    survival-kit-dev = books.devguide;
  };
  # clean file names → clean book URLs (store paths would leak the hash)
  starterDir = pkgs.linkFarm "kiwix-starter" (
    lib.mapAttrsToList (name: path: {
      name = "${name}.zim";
      inherit path;
    }) starterZims
  );
in
{
  options.survivalKit.services.kiwix = {
    enable = lib.mkEnableOption "Kiwix offline wiki (kiwix-serve)";
    starterContent = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Bundle the starter ZIMs (Linux/Nix docs, survival-kit manual) in the image.";
    };
  };

  config = lib.mkIf cfg.enable {
    services.kiwix-serve = {
      enable = true;
      address = "127.0.0.1";
      inherit port;
      libraryPath = "${dataDir}/library.xml";
      extraArgs = [ "--monitorLibrary" ]; # reload when library.xml changes
    };

    # every catalog refresh restarts kiwix-serve (see the script's end): allow quick
    # successive refreshes (default limit: 5 starts / 10 s), but still stop a crash loop
    # (Restart=on-failure, ~0.1 s apart → 20 starts within ~2 s)
    systemd.services.kiwix-serve.unitConfig.StartLimitBurst = 20;

    systemd.services.kiwix-library = {
      description = "Rebuild the Kiwix catalog from available ZIM files";
      # Wants (not Requires): if a rebuild fails, kiwix-serve keeps running on the
      # last good library.xml. A successful rebuild restarts kiwix-serve (end of
      # script) — --monitorLibrary alone misses a 2nd rebuild within the same
      # second (mtime has 1 s granularity).
      wantedBy = [
        "multi-user.target"
        "kiwix-serve.service"
      ];
      before = [ "kiwix-serve.service" ];
      path = [ config.services.kiwix-serve.package ];
      # re-run on demand (after adding ZIMs, later by an import tile): no systemd
      # start limit — the default (5 starts / 10 s) refuses quick successive refreshes
      startLimitIntervalSec = 0;
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        install -d -m 0755 ${dataDir} ${dataDir}/zims
        tmp=$(mktemp --suffix=.xml ${dataDir}/.library.XXXXXX)
        trap 'rm -f "$tmp"' EXIT # no leftover temp catalogs if anything fails
        printf '<library version="20110515"></library>\n' > "$tmp"
        shopt -s nullglob
        # say what is ignored instead of skipping it silently
        for f in ${dataDir}/zims/*; do
          [[ $f == *.zim ]] ||
            echo "kiwix-library: ignoring $f: not a .zim file (rename .ZIM; join split .zimaa/.zimab parts first)" >&2
        done
        ${lib.optionalString cfg.starterContent ''
          for zim in ${starterDir}/*.zim; do
            kiwix-manage "$tmp" add "$zim" || echo "kiwix-library: skipping unreadable $zim" >&2
          done
        ''}
        for zim in ${dataDir}/zims/*.zim; do
          # chmod: kiwix-serve runs as an unprivileged DynamicUser. Guarded like
          # kiwix-manage — one odd entry (dangling link, read-only media) must not
          # abort the rebuild (the script runs under `set -e`).
          { chmod a+r "$zim" && kiwix-manage "$tmp" add "$zim"; } ||
            echo "kiwix-library: skipping unreadable $zim" >&2
        done
        chmod 0644 "$tmp"
        mv -f "$tmp" ${dataDir}/library.xml # atomic: kiwix-serve never sees a half-written file
        # reload a running server; no-op at boot (not started yet). --no-block:
        # don't wait on a job that is itself ordered after this unit.
        ${config.systemd.package}/bin/systemctl --no-block try-restart kiwix-serve.service
      '';
    };

    survivalKit = {
      registry.kiwix = {
        subdomain = "wiki";
        inherit port;
        title = "Wiki";
        description = "Offline encyclopedias, Linux & Nix docs";
        order = 10;
      };
      dashboard.links = lib.mkIf cfg.starterContent {
        manual = {
          title = "Manual";
          description = "How to use and maintain this box";
          url = "http://wiki.${config.survivalKit.web.domain}/content/survival-kit";
          order = 20;
        };
        devguide = {
          title = "Developer guide";
          description = "How survival-kit is built, and how to change it";
          url = "http://wiki.${config.survivalKit.web.domain}/content/survival-kit-dev";
          order = 30;
        };
      };
    };
  };
}
