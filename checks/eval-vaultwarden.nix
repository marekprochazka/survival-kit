# Layer 2 — eval assertions: Vaultwarden (passwords) behind nginx, offline-friendly.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  cfg = self.nixosConfigurations.survival-kit.config;
  vw = cfg.services.vaultwarden;
  reg = cfg.survivalKit.registry.vault;
  unit = cfg.systemd.services.vaultwarden;
in
assert lib.assertMsg vw.enable "vaultwarden must be enabled";
assert lib.assertMsg (
  vw.config.ROCKET_ADDRESS == "127.0.0.1" && vw.config.ROCKET_PORT == 8222
) "vaultwarden listens on 127.0.0.1:8222 only (nginx in front)";
assert lib.assertMsg (
  vw.config.DOMAIN == "https://vault.deck"
) "DOMAIN must be the https URL (links in the web vault)";
assert lib.assertMsg (vw.config.SIGNUPS_ALLOWED == true) "open signups (user decision)";
assert lib.assertMsg (vw.backupDir == "/var/backup/vaultwarden") "daily backups must be on";
assert lib.assertMsg (
  !(lib.elem "network-online.target" (unit.wants ++ unit.after))
) "a loopback-only service must not wait for the network";
assert lib.assertMsg (
  reg.port == 8222 && reg.subdomain == "vault" && reg.healthPath == "/alive"
) "registry entry vault: port 8222, health /alive";
assert lib.assertMsg cfg.services.nginx.virtualHosts."vault.deck".locations."/".proxyWebsockets
  "vault.deck must pass WebSockets through (live sync)";
pkgs.runCommand "eval-vaultwarden" { } "touch $out"
