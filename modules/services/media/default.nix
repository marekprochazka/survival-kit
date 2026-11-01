# Media (spec 2026-11-01-media) at https://media.<domain>: Jellyfin for films, series and
# music, offline. The media itself lives in the content tree on every location (media/) and
# reaches Jellyfin through the library index (library/media/{movies,shows,music}); the
# Content page imports and deletes it. First boot hands the owner's name and password to
# survival-kit-media-setup (./app/setup.py), which sets Jellyfin up once — after that every
# Jellyfin setting is the owner's. The library asks Jellyfin to rescan with the box's key.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.services.media;
  jf = config.services.jellyfin;
  port = 8096;
  url = "http://127.0.0.1:${toString port}";
  setup = pkgs.writeShellApplication {
    name = "survival-kit-media-setup";
    text = ''
      export MEDIA_URL=${url}
      export MEDIA_KEY_FILE=${cfg.keyFile}
      export MEDIA_LIBRARY=${config.survivalKit.storage.libraryDir}/media
      exec ${pkgs.python3}/bin/python3 ${./app/setup.py} "$@"
    '';
  };
in
{
  options.survivalKit.services.media = {
    enable = lib.mkEnableOption "Media (Jellyfin: films, series and music)";
    keyFile = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/survival-kit/media/api-key";
      readOnly = true;
      description = "The box's Jellyfin key (root only), made at first setup; used only to ask for rescans.";
    };
    setupCommand = lib.mkOption {
      type = lib.types.str;
      default = lib.getExe setup;
      defaultText = lib.literalExpression "survival-kit-media-setup";
      readOnly = true;
      description = "Sets Jellyfin up once: reads the owner's name and password from stdin.";
    };
  };

  config = lib.mkIf cfg.enable {
    services.jellyfin.enable = true; # openFirewall stays false: nginx is the way in

    systemd.services.jellyfin = {
      # upstream waits for network-online: pointless for a loopback-only service on an
      # offline box (it would hold Media back when no network comes up)
      wants = lib.mkForce [ ];
      after = lib.mkForce [ ];
      # a fresh Jellyfin listens on all interfaces; the box's starts on 127.0.0.1 only (nginx
      # in front), no UPnP, no discovery broadcast. Written once: later it is the owner's file.
      preStart = ''
        if [ ! -e ${jf.configDir}/network.xml ]; then
          mkdir -p ${jf.configDir}
          cat > ${jf.configDir}/network.xml <<'EOF'
        <?xml version="1.0" encoding="utf-8"?>
        <NetworkConfiguration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
          <InternalHttpPort>${toString port}</InternalHttpPort>
          <EnableIPv6>false</EnableIPv6>
          <LocalNetworkAddresses>
            <string>127.0.0.1</string>
          </LocalNetworkAddresses>
          <EnableUPnP>false</EnableUPnP>
          <AutoDiscovery>false</AutoDiscovery>
          <EnableRemoteAccess>false</EnableRemoteAccess>
        </NetworkConfiguration>
        EOF
        fi
      '';
      serviceConfig = {
        # scans and sound conversion give way to the desktop (modules/base)
        Slice = "background.slice";
        IOSchedulingClass = "best-effort";
        IOSchedulingPriority = 6;
      };
    };

    # after every import, delete or drive change the library is rebuilt: then it asks
    # Jellyfin to rescan (no file watching — it misses changes behind links and on drives)
    systemd.services.survival-kit-library.environment = {
      MEDIA_KEY_FILE = cfg.keyFile;
      MEDIA_URL = url;
    };

    environment.systemPackages = [ setup ];

    survivalKit.registry.media = {
      subdomain = "media";
      inherit port;
      title = "Media";
      description = "Films, series and music";
      order = 18; # after Inventory (17)
      healthPath = "/health";
    };
  };
}
