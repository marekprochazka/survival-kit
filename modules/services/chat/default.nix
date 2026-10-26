# Wiki-first chat (ADR-0005) at https://chat.<domain>: ask the local AI; the box looks in the
# wiki first (via the lookup service) and answers with links, or says it didn't find it.
# Chats in SQLite, one answer at a time (a job queue), answers run on the box even when the
# page is closed. Python stdlib (./app). Full profile only (needs Ollama).
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.services.chat;
  port = 8320;
  static = pkgs.runCommand "chat-static" { } ''
    mkdir $out
    cp ${./app/static}/* $out/
    cp ${../../dashboard/style.css} $out/style.css
  '';
in
{
  options.survivalKit.services.chat = {
    enable = lib.mkEnableOption "the wiki-first chat page";
    ollamaUrl = lib.mkOption {
      type = lib.types.str;
      default = "http://127.0.0.1:11434";
      internal = true; # VM tests point it at a stand-in model server
      description = "Where the chat and the lookup's planning step reach Ollama.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.survivalKit.services.ollama.enable && config.survivalKit.services.lookup.enable;
        message = "survivalKit.services.chat needs Ollama and the wiki lookup";
      }
    ];

    systemd.services.survival-kit-chat = {
      description = "survival-kit wiki-first chat";
      wantedBy = [ "multi-user.target" ];
      after = [
        "survival-kit-lookup.service"
        "ollama.service"
      ];
      wants = [
        "survival-kit-lookup.service"
        "ollama.service"
      ];
      environment = {
        CHAT_PORT = toString port;
        CHAT_DB = "/var/lib/survival-kit/chat/chats.db";
        LOOKUP_URL = "http://127.0.0.1:8310";
        OLLAMA_URL = cfg.ollamaUrl;
        STATIC_DIR = "${static}";
        PYTHONUNBUFFERED = "1";
      };
      serviceConfig = {
        ExecStart = "${pkgs.python3}/bin/python3 ${./app}/server.py";
        DynamicUser = true;
        StateDirectory = "survival-kit/chat"; # the only place it can write
        Restart = "on-failure";
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        NoNewPrivileges = true;
      };
    };

    survivalKit.registry.chat = {
      subdomain = "chat";
      inherit port;
      title = "Chat";
      description = "Ask the local AI — it looks things up in the wiki first";
      order = 12; # right after Wiki
      healthPath = "/health";
    };

    # the answer streams live (Server-Sent Events): no buffering, long-lived connections
    services.nginx.virtualHosts."chat.${config.survivalKit.web.domain}".extraConfig = ''
      proxy_buffering off;
      proxy_read_timeout 3600s;
    '';
  };
}
