# Offline maps (ADR-0002, amended) at https://maps.<domain>: no map server — nginx serves a
# static page (MapLibre + Protomaps style, fonts, icons) and the .pmtiles files; the browser
# fetches only the byte ranges it needs and draws the map. Built-in maps come from the Nix
# store (/builtin/), imported ones from the content library (/imported/: links to the maps in
# use on this device and on added drives, ADR-0006).
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.services.maps;
  importDir = "${config.survivalKit.storage.libraryDir}/maps";
  # vendored, pinned by hash; licences ship next to them (THIRD-PARTY.md)
  maplibre = pkgs.fetchurl {
    url = "https://registry.npmjs.org/maplibre-gl/-/maplibre-gl-6.14.0.tgz";
    hash = "sha256-95loLnotGJ5D0YzPaInQnR6FR+LKtLp51zYMyWYwIH4=";
  };
  pmtilesJs = pkgs.fetchurl {
    url = "https://registry.npmjs.org/pmtiles/-/pmtiles-4.5.0.tgz";
    hash = "sha256-I658V1V4rSTNV5N31pxGVQYx2iGebxeZl+ws87jJN+U=";
  };
  basemaps = pkgs.fetchurl {
    url = "https://registry.npmjs.org/@protomaps/basemaps/-/basemaps-5.7.2.tgz";
    hash = "sha256-LV1BspzdI2T3CSrUOb2dFwtPOMvsiFjO++hND5gSXOY=";
  };
  assets = pkgs.fetchFromGitHub {
    owner = "protomaps";
    repo = "basemaps-assets";
    rev = "028c18f713baecad011301ff7a69acc39bcc2ae7";
    hash = "sha256-P52xWPZr59voAumONX/n8g15xxqgqyXYIRoZmNSawAw=";
  };
  # the npm tarballs carry no licence file: pinned copies from the upstream repos
  pmtilesLicense = pkgs.fetchurl {
    url = "https://raw.githubusercontent.com/protomaps/PMTiles/aec8fa1341222fdddb3318e9ffa8e18e19b312f7/LICENSE";
    hash = "sha256-A3HDjzOINff8E+1xF289khROIsi3NqMcztV62762R7M=";
  };
  basemapsLicense = pkgs.fetchurl {
    url = "https://raw.githubusercontent.com/protomaps/basemaps/42ffaaa4a85a41bfcb23e43cc0f5b492a5eca123/LICENSE.md";
    hash = "sha256-dPl1z+3RaAmMQ7XP1uWH5AYEaExP/Ow+kNJLOwnAYbA=";
  };

  site = pkgs.runCommand "maps-site" { } ''
    mkdir -p $out/vendor/maplibre $out/sprites $out/licenses
    cp ${./site}/* $out/
    cp ${../../dashboard/style.css} $out/style.css
    tar xzf ${maplibre} --strip-components=2 -C $out/vendor/maplibre \
      package/dist/maplibre-gl.mjs package/dist/maplibre-gl-shared.mjs \
      package/dist/maplibre-gl-worker.mjs package/dist/maplibre-gl.css
    tar xzf ${pmtilesJs} --strip-components=2 -C $out/vendor package/dist/pmtiles.js
    tar xzf ${basemaps} --strip-components=2 -C $out/vendor package/dist/basemaps.js
    cp -r ${assets}/fonts $out/fonts # all of it: ~14 MB, every script Noto Sans has
    cp -r ${assets}/sprites/v4 $out/sprites/v4
    tar xzf ${maplibre} -O package/LICENSE.txt > $out/licenses/maplibre-LICENSE
    cp ${pmtilesLicense} $out/licenses/pmtiles-LICENSE
    cp ${basemapsLicense} $out/licenses/basemaps-LICENSE.md
    cp ${assets}/fonts/OFL.txt $out/licenses/fonts-OFL.txt
  '';
  # one JSON listing per folder: [{"name":"czechia.pmtiles","type":"file","size":…}, …]
  listing = ''
    autoindex on;
    autoindex_format json;
    add_header Cache-Control "no-cache"; # an import may replace a map of the same name
  '';
in
{
  options.survivalKit.services.maps = {
    enable = lib.mkEnableOption "offline maps";
    builtins = lib.mkOption {
      type = lib.types.attrsOf lib.types.path;
      default = (import ./builtins.nix { inherit pkgs; }).maps;
      defaultText = lib.literalMD "the maps pinned by `utils/fetch-maps`";
      description = "Built-in maps, name → .pmtiles (VM tests use small stand-ins).";
    };
    builtinDir = lib.mkOption {
      type = lib.types.path;
      readOnly = true;
      description = "The built-in maps as <name>.pmtiles (for the content manager).";
    };
  };

  config = lib.mkIf cfg.enable {
    survivalKit.services.maps.builtinDir = pkgs.linkFarm "maps-builtin" (
      lib.mapAttrsToList (name: path: {
        name = "${name}.pmtiles";
        inherit path;
      }) cfg.builtins
    );

    survivalKit.registry.maps = {
      subdomain = "maps";
      root = site;
      title = "Maps";
      description = "Offline maps of Central Europe and Czechia";
      order = 11; # after Wiki (10), before Chat (12)
      healthPath = "/index.html";
    };

    services.nginx.virtualHosts."maps.${config.survivalKit.web.domain}".locations = {
      "/builtin/" = {
        alias = "${cfg.builtinDir}/";
        extraConfig = listing;
      };
      "/imported/" = {
        alias = "${importDir}/";
        extraConfig = listing;
      };
      # never serve dot-paths; a regex location wins over the prefix ones above
      "~ /\\." = {
        return = "404";
      };
    };
  };
}
