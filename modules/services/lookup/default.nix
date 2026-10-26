# Wiki lookup (ADR-0005): what does the box's wiki say about a question? Book map (Kiwix
# catalog) → the model picks books + search words → full-text search → read the articles.
# Two front doors: an internal HTTP API for the chat (127.0.0.1:8310, no vhost) and an MCP
# server over stdio (`survival-kit-wiki-mcp`) for MCP clients such as oterm or mcphost.
# Python stdlib (./app). Comes with the wiki: on both profiles.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.services.lookup;
  port = 8310;
  wikiEnv = {
    KIWIX_URL = "http://127.0.0.1:${toString config.services.kiwix-serve.port}";
    PUBLIC_WIKI_URL = "https://wiki.${config.survivalKit.web.domain}";
  };
  mcp = pkgs.writeShellApplication {
    name = "survival-kit-wiki-mcp";
    runtimeInputs = [ pkgs.python3 ];
    text = ''
      export KIWIX_URL=${lib.escapeShellArg wikiEnv.KIWIX_URL}
      export PUBLIC_WIKI_URL=${lib.escapeShellArg wikiEnv.PUBLIC_WIKI_URL}
      exec python3 ${./app}/mcp.py "$@"
    '';
  };
in
{
  options.survivalKit.services.lookup.enable =
    lib.mkEnableOption "the wiki lookup service and its MCP command";

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.survivalKit.services.kiwix.enable;
        message = "survivalKit.services.lookup needs the wiki (survivalKit.services.kiwix)";
      }
    ];

    systemd.services.survival-kit-lookup = {
      description = "survival-kit wiki lookup";
      wantedBy = [ "multi-user.target" ];
      after = [ "kiwix-serve.service" ];
      wants = [ "kiwix-serve.service" ];
      environment = wikiEnv // {
        LOOKUP_PORT = toString port;
        OLLAMA_URL = config.survivalKit.services.chat.ollamaUrl; # the planning step
        PYTHONUNBUFFERED = "1";
      };
      serviceConfig = {
        ExecStart = "${pkgs.python3}/bin/python3 ${./app}/server.py";
        DynamicUser = true; # no state, no rights: it only reads the wiki over HTTP
        Restart = "on-failure";
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        NoNewPrivileges = true;
      };
    };

    environment.systemPackages = [ mcp ];
  };
}
