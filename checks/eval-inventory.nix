# Layer 2 — eval assertions: Inventory (Homebox) behind nginx, offline, both profiles.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  base = self.nixosConfigurations.survival-kit;
  cfg = base.config;
  lite = (base.extendModules { modules = [ { survivalKit.profile = "lite"; } ]; }).config;
  hb = cfg.services.homebox;
  set = hb.settings;
  reg = cfg.survivalKit.registry.inventory;
  unit = cfg.systemd.services.homebox;
in
assert lib.assertMsg hb.enable "homebox must be enabled (full)";
assert lib.assertMsg lite.services.homebox.enable "homebox must be enabled in lite too";
assert lib.assertMsg (
  set.HBOX_WEB_HOST == "127.0.0.1" && set.HBOX_WEB_PORT == "7745"
) "homebox listens on 127.0.0.1:7745 only (nginx in front)";
assert lib.assertMsg (
  set.HBOX_OPTIONS_ALLOW_REGISTRATION == "true"
) "open sign-up (decided; upstream default is off)";
# upstream's module sets HBOX_OPTIONS_CHECK_GITHUB_RELEASE, a name Homebox 0.25 never reads
assert lib.assertMsg (
  set.HBOX_OPTIONS_GITHUB_RELEASE_CHECK == "false"
) "no release check — the box is offline";
assert lib.assertMsg
  (set.HBOX_OPTIONS_TRUST_PROXY == "true" && set.HBOX_OPTIONS_HOSTNAME == "https://inventory.deck")
  "behind nginx: trust its forwarded headers, absolute links (invitations) on https://inventory.deck";
assert lib.assertMsg (
  (set.HBOX_OTEL_ENABLED or "false") == "false"
  && (set.HBOX_OPTIONS_ALLOW_ANALYTICS or "false") == "false"
) "no telemetry, no analytics";
assert lib.assertMsg (set.HBOX_WEB_MAX_UPLOAD_SIZE == "32") "uploads up to 32 MB (phone photos)";
assert lib.assertMsg (lib.hasInfix "client_max_body_size 32m;"
  cfg.services.nginx.virtualHosts."inventory.deck".extraConfig
) "nginx must let 32 MB uploads through (its default is 1 MB)";
assert lib.assertMsg (
  !(lib.elem "network-online.target" (unit.wants ++ unit.after))
) "a loopback-only service must not wait for the network";
assert lib.assertMsg (
  reg.port == 7745
  && reg.subdomain == "inventory"
  && reg.healthPath == "/api/v1/status"
  && reg.order == 17
  && reg.title == "Inventory"
) "registry entry inventory: port 7745, health /api/v1/status, order 17";
pkgs.runCommand "eval-inventory" { } "touch $out"
