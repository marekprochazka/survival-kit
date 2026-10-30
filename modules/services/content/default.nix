# Content manager (ADR-0004) at https://content.<domain>: import wiki books, maps and AI
# models through the browser's file dialog, see disk use, delete. A small Python program (stdlib
# only, ./app) behind nginx; file-based with system rights — it never logs into a service.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.services.content;
  kiwix = config.survivalKit.services.kiwix;
  port = 8300;
  # this device's content tree (ADR-0006); the library links what is in use for the services
  zims = "${config.survivalKit.storage.dataDir}/wiki";
  stateDir = "/var/lib/survival-kit/content";
  ollama = config.services.ollama.enable;
  maps = config.survivalKit.services.maps;
  mapsDir = "${config.survivalKit.storage.dataDir}/maps";
  # the page + the dashboard's look
  static = pkgs.runCommand "content-static" { } ''
    mkdir $out
    cp ${./app/static}/* $out/
    cp ${../../dashboard/style.css} $out/style.css
  '';
in
{
  options.survivalKit.services.content.enable =
    lib.mkEnableOption "the content manager (import and manage wiki books, maps and AI models)";

  config = lib.mkIf cfg.enable {
    systemd.services.survival-kit-content = {
      description = "survival-kit content manager";
      wantedBy = [ "multi-user.target" ];
      # the library creates this device's tree; models need the local Ollama
      after = [ "survival-kit-library.service" ] ++ lib.optional ollama "ollama.service";
      wants = [ "survival-kit-library.service" ] ++ lib.optional ollama "ollama.service";
      path = [
        pkgs.kiwix-tools # kiwix-manage: is an uploaded book readable?
        config.systemd.package # systemctl restart kiwix-library
      ]
      ++ lib.optional ollama config.services.ollama.package;
      environment = {
        CONTENT_PORT = toString port;
        ZIMS_DIR = zims;
        STATE_DIR = stateDir;
        STATIC_DIR = "${static}";
        BUILTINS_DIR = lib.optionalString (kiwix.starterDir != null) "${kiwix.starterDir}";
        PROTECTED = config.systemd.services.survival-kit-library.environment.PROTECTED;
        OLLAMA = if ollama then "1" else "0";
        MODELS_DIR = config.services.ollama.models;
        LOOKUP_URL = lib.optionalString config.survivalKit.services.lookup.enable "http://127.0.0.1:8310";
        # maps: imports land in this device's tree; the library links them for nginx
        MAPS_DIR = lib.optionalString maps.enable mapsDir;
        MAP_BUILTINS_DIR = lib.optionalString maps.enable "${maps.builtinDir}";
        MAP_SCHEME = "4"; # Protomaps basemap version the bundled map style draws
        PYTHONUNBUFFERED = "1";
        # the ollama CLI panics without a $HOME (it derives ~/.ollama even as a client)
        HOME = stateDir;
      };
      serviceConfig = {
        ExecStart = "${pkgs.python3}/bin/python3 ${./app}/server.py";
        StateDirectory = "survival-kit/content";
        Restart = "on-failure";
        # root (writes into the content tree, rebuilds the library) — but confined:
        ProtectSystem = "strict";
        ReadWritePaths = [
          zims
          stateDir
        ]
        ++ lib.optional maps.enable mapsDir;
        ProtectHome = true;
        PrivateTmp = true;
        NoNewPrivileges = true;
      };
    };

    survivalKit.registry.content = {
      subdomain = "content";
      inherit port;
      title = "Content";
      description = "Import and manage wiki books, maps and AI models";
      order = 40;
      healthPath = "/health";
    };

    # large uploads (models: GBs), streamed to the service instead of buffered by nginx
    services.nginx.virtualHosts."content.${config.survivalKit.web.domain}".extraConfig = ''
      client_max_body_size 0;
      proxy_request_buffering off;
      proxy_read_timeout 3600s;
      proxy_send_timeout 3600s;
    '';
  };
}
