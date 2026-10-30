# Layer 2 — eval assertions: the content manager (ADR-0004) — registry, nginx for large
# streamed uploads, a confined service, Ollama only on full.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  cfg = self.nixosConfigurations.survival-kit.config;
  reg = cfg.survivalKit.registry.content;
  vhost = cfg.services.nginx.virtualHosts."content.deck";
  svc = cfg.systemd.services.survival-kit-content;
in
assert lib.assertMsg cfg.survivalKit.services.content.enable "the content manager must be on";
assert lib.assertMsg (
  reg.port == 8300 && reg.subdomain == "content" && reg.healthPath == "/health"
) "registry entry content: port 8300, health /health";
assert lib.assertMsg (
  lib.hasInfix "client_max_body_size 0" vhost.extraConfig
  && lib.hasInfix "proxy_request_buffering off" vhost.extraConfig
) "content.deck must take large uploads, streamed (no size limit, no buffering)";
assert lib.assertMsg (svc.serviceConfig.ProtectSystem == "strict") "the service runs confined";
assert lib.assertMsg (
  lib.sort lib.lessThan svc.serviceConfig.ReadWritePaths == [
    "/var/lib/survival-kit/content"
    "/var/lib/survival-kit/data"
    "/var/lib/survival-kit/drives"
    "/var/lib/survival-kit/set-aside"
  ]
) "the service may write only to its own dir, the content trees and the set-aside dir";
assert lib.assertMsg (
  svc.environment.REGISTRY == "/var/lib/survival-kit/content/drives.json"
  && svc.environment.DATA_DIR == "/var/lib/survival-kit/data"
) "added drives are listed in the service's own dir; this device's tree";
assert lib.assertMsg (
  svc.environment.MAPS == "1"
  && svc.environment.MAP_SCHEME == "4"
  && svc.environment.MAP_BUILTINS_DIR == "${cfg.survivalKit.services.maps.builtinDir}"
) "maps section: imports dir, built-in maps, Protomaps scheme 4";
assert lib.assertMsg (
  reg.description == "Import and manage wiki books, maps and AI models"
) "the tile names all three kinds";
assert lib.assertMsg (svc.environment.OLLAMA == "1") "full: the models section is on";
assert lib.assertMsg (
  svc.environment.HOME == "/var/lib/survival-kit/content"
) "the ollama CLI needs a $HOME (it panics without one); the service's own dir";
pkgs.runCommand "eval-content" { } "touch $out"
