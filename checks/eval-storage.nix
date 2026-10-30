# Layer 2 — eval assertions: content storage (ADR-0006) — the library is rebuilt before the
# wiki's catalog, and Kiwix and the maps site read the library, not per-service folders.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  cfg = self.nixosConfigurations.survival-kit.config;
  lib' = cfg.systemd.services.survival-kit-library;
  kiwixScript = cfg.systemd.services.kiwix-library.script;
  imported = cfg.services.nginx.virtualHosts."maps.deck".locations."/imported/";
in
assert lib.assertMsg (
  cfg.survivalKit.storage.libraryDir == "/var/lib/survival-kit/library"
) "the library lives at /var/lib/survival-kit/library";
assert lib.assertMsg (
  lib.elem "kiwix-library.service" lib'.before && lib.elem "survival-kit-drives.service" lib'.after
) "order: drives mounted → library rebuilt → wiki catalog";
assert lib.assertMsg (lib'.serviceConfig.ProtectSystem == "strict") "the library runs confined";
assert lib.assertMsg (
  lib.hasInfix "/var/lib/survival-kit/library/wiki" kiwixScript
  && !(lib.hasInfix "kiwix/zims" kiwixScript)
) "Kiwix's catalog is built from the library, not its own drop-in dir";
assert lib.assertMsg (
  imported.alias == "/var/lib/survival-kit/library/maps/"
) "imported maps are served from the library";
pkgs.runCommand "eval-storage" { } "touch $out"
