# Layer 2 — eval assertions: Media (Jellyfin) behind nginx, both profiles, the shared
# background slice, the one-time setup helper and the library's rescan key.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  base = self.nixosConfigurations.survival-kit;
  cfg = base.config;
  lite = (base.extendModules { modules = [ { survivalKit.profile = "lite"; } ]; }).config;
  jf = cfg.services.jellyfin;
  reg = cfg.survivalKit.registry.media;
  media = cfg.survivalKit.services.media;
  unit = cfg.systemd.services.jellyfin;
  library = cfg.systemd.services.survival-kit-library.environment;
in
assert lib.assertMsg jf.enable "jellyfin must be enabled (full)";
assert lib.assertMsg lite.services.jellyfin.enable "jellyfin must be enabled in lite too";
assert lib.assertMsg (
  reg.port == 8096
  && reg.subdomain == "media"
  && reg.healthPath == "/health"
  && reg.order == 18
  && reg.title == "Media"
  && reg.description == "Films, series and music"
) "registry entry media: port 8096, health /health, order 18";
assert lib.assertMsg (
  !jf.openFirewall && cfg.networking.firewall.enable
) "Jellyfin is reached through nginx only: its own port stays closed";
assert lib.assertMsg (
  unit.serviceConfig.Slice == "background.slice"
  && lite.systemd.slices.background.sliceConfig.CPUWeight == 20
) "Jellyfin's scans give way to the desktop (background slice, in lite too)";
assert lib.assertMsg (
  lib.hasInfix "<string>127.0.0.1</string>" unit.preStart && lib.hasInfix "[ ! -e " unit.preStart
) "a fresh Jellyfin listens on 127.0.0.1 only — written once, never over the owner's settings";
assert lib.assertMsg (
  library.MEDIA_KEY_FILE == media.keyFile
  && library.MEDIA_URL == "http://127.0.0.1:8096"
  && media.keyFile == "/var/lib/survival-kit/media/api-key"
) "the library asks Jellyfin to rescan with the box's key";
assert lib.assertMsg (
  cfg.systemd.services.survival-kit-content.environment.MEDIA == "1"
) "the content manager shows the Media section";
assert lib.assertMsg (lib.hasSuffix "/bin/survival-kit-media-setup" media.setupCommand)
  "the one-time setup helper is packaged";
assert lib.assertMsg (
  !(lib.elem "network-online.target" (unit.wants ++ unit.after))
) "a loopback-only service must not wait for the network";
assert lib.assertMsg (
  let
    r = cfg.systemd.services.survival-kit-media-rescan;
  in
  lib.elem "jellyfin.service" r.wantedBy
  && lib.elem "jellyfin.service" r.after
  && lib.hasInfix "library.py notify-media" r.serviceConfig.ExecStart
  && r.environment.MEDIA_KEY_FILE == media.keyFile
) "after every Jellyfin start (boot too) the box asks for a rescan once it answers";
assert lib.assertMsg (
  unit.serviceConfig.LimitCORE == 0
  && unit.unitConfig.StartLimitBurst == 5
  && unit.unitConfig.StartLimitIntervalSec == 600
) "Jellyfin refuses to start below 2 GiB free: no core dumps (~180 MB each) and a restart limit";
pkgs.runCommand "eval-media" { } "touch $out"
