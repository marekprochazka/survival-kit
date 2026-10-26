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
    "/var/lib/survival-kit/kiwix/zims"
  ]
) "the service may write only to its own dir and the wiki's drop-in dir";
assert lib.assertMsg (svc.environment.OLLAMA == "1") "full: the models section is on";
assert lib.assertMsg (
  svc.environment.HOME == "/var/lib/survival-kit/content"
) "the ollama CLI needs a $HOME (it panics without one); the service's own dir";
pkgs.runCommand "eval-content" { } "touch $out"
