# Layer 2 — eval assertions: offline maps (ADR-0002 amended) — a static site in the registry,
# nginx listings for built-in and imported maps, no dot-paths served, on in both profiles.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  base = self.nixosConfigurations.survival-kit;
  cfg = base.config;
  lite = (base.extendModules { modules = [ { survivalKit.profile = "lite"; } ]; }).config;
  reg = cfg.survivalKit.registry.maps;
  locs = cfg.services.nginx.virtualHosts."maps.deck".locations;
  json = loc: lib.hasInfix "autoindex_format json" locs.${loc}.extraConfig;
  builtinNames = map (n: "${n}.pmtiles") (lib.attrNames cfg.survivalKit.services.maps.builtins);
in
assert lib.assertMsg (
  cfg.survivalKit.services.maps.enable && lite.survivalKit.services.maps.enable
) "maps must be on in both profiles";
assert lib.assertMsg (
  reg.root != null && reg.port == null && reg.subdomain == "maps"
) "registry entry maps: a static site at maps.deck";
assert lib.assertMsg (
  reg.order == 11 && reg.healthPath == "/index.html"
) "maps: order 11 (after Wiki), health = the page file";
assert lib.assertMsg (
  json "/builtin/" && json "/imported/"
) "built-in and imported maps are listed as nginx JSON";
assert lib.assertMsg (
  locs."/imported/".alias == "/var/lib/survival-kit/library/maps/"
) "imported maps come from the content library (ADR-0006)";
assert lib.assertMsg (locs."~ /\\.".return == "404") "dot-paths are never served";
assert lib.assertMsg (
  lib.sort lib.lessThan builtinNames == [
    "central-europe.pmtiles"
    "czechia.pmtiles"
    "world.pmtiles"
  ]
) "built-in maps: world, central-europe, czechia";
pkgs.runCommand "eval-maps" { } "touch $out"
