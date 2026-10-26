# Layer 2 — eval assertions: the wiki-first chat (ADR-0005) — lookup + MCP command, the chat
# service (full only), nginx for live events.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  cfg = self.nixosConfigurations.survival-kit.config;
  chat = cfg.systemd.services.survival-kit-chat;
  look = cfg.systemd.services.survival-kit-lookup;
  reg = cfg.survivalKit.registry.chat;
in
assert lib.assertMsg (
  reg.port == 8320 && reg.subdomain == "chat" && reg.order == 12 && reg.healthPath == "/health"
) "registry entry chat: port 8320, order 12, health /health";
assert lib.assertMsg (
  chat.serviceConfig.DynamicUser && chat.serviceConfig.StateDirectory == "survival-kit/chat"
) "the chat runs as a dynamic user and writes only its own state dir";
assert lib.assertMsg (
  look.serviceConfig.DynamicUser && !(look.serviceConfig ? StateDirectory)
) "the lookup keeps no state";
assert lib.assertMsg (lib.any (
  p: lib.getName p == "survival-kit-wiki-mcp"
) cfg.environment.systemPackages) "the MCP command is installed";
assert lib.assertMsg (lib.hasInfix "proxy_buffering off"
  cfg.services.nginx.virtualHosts."chat.deck".extraConfig
) "chat.deck must not buffer the live answer stream";
assert lib.assertMsg (
  chat.environment.LOOKUP_URL == "http://127.0.0.1:8310"
) "the chat asks the lookup service";
pkgs.runCommand "eval-chat" { } "touch $out"
