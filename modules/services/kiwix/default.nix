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
  starterZims = import ./zims.nix { inherit pkgs; };
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

    systemd.services.kiwix-library = {
      description = "Rebuild the Kiwix catalog from available ZIM files";
      wantedBy = [ "multi-user.target" ];
      before = [ "kiwix-serve.service" ];
      requiredBy = [ "kiwix-serve.service" ];
      path = [ config.services.kiwix-serve.package ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        install -d -m 0755 ${dataDir} ${dataDir}/zims
        tmp=$(mktemp --suffix=.xml ${dataDir}/.library.XXXXXX)
        printf '<library version="20110515"></library>\n' > "$tmp"
        shopt -s nullglob
        ${lib.optionalString cfg.starterContent ''
          for zim in ${starterDir}/*.zim; do
            kiwix-manage "$tmp" add "$zim" || echo "kiwix-library: skipping unreadable $zim" >&2
          done
        ''}
        for zim in ${dataDir}/zims/*.zim; do
          chmod a+r "$zim" # kiwix-serve runs as an unprivileged DynamicUser
          kiwix-manage "$tmp" add "$zim" || echo "kiwix-library: skipping unreadable $zim" >&2
        done
        chmod 0644 "$tmp"
        mv -f "$tmp" ${dataDir}/library.xml # atomic: kiwix-serve never sees a half-written file
      '';
    };

    survivalKit.registry.kiwix = {
      subdomain = "wiki";
      inherit port;
      title = "Wiki";
      description = "Offline encyclopedias, Linux & Nix docs";
      order = 10;
    };
  };
}
