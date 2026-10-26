# Dashboard at http://<domain> (ADR-0002 §5): static HTML rendered at build
# time from the service registry + extra links. Works without JS; status.js
# only adds live up/down dots via the same-origin /health/<name> endpoints.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  inherit (lib) mkOption types;
  inherit (config.survivalKit) registry dashboard;
  inherit (config.survivalKit.web) domain;
  inherit (config.networking) hostName;
  esc = lib.escapeXML;

  serviceTiles = lib.mapAttrsToList (name: svc: {
    inherit name;
    inherit (svc) title description order;
    url = "http://${svc.subdomain}.${domain}/";
    health = "/health/${name}";
  }) registry;
  linkTiles = lib.mapAttrsToList (name: link: {
    inherit name;
    inherit (link)
      title
      description
      order
      url
      ;
    health = null;
  }) dashboard.links;
  tiles = lib.sort (a: b: if a.order == b.order then a.name < b.name else a.order < b.order) (
    serviceTiles ++ linkTiles
  );

  renderTile =
    t:
    let
      isService = t.health != null;
    in
    ''
      <a class="tile" href="${esc t.url}"${lib.optionalString isService " data-health=\"${esc t.health}\""}>
        <span class="title">${esc t.title}</span>${lib.optionalString isService "<span class=\"dot\" role=\"img\" aria-label=\"status unknown\"></span>"}
        <span class="desc">${esc t.description}</span>
      </a>
    '';

  page = pkgs.writeText "index.html" ''
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>${esc hostName}</title>
      <link rel="stylesheet" href="style.css">
    </head>
    <body>
      <header>
        <h1>${esc hostName}</h1>
        <p>Everything here works offline.</p>
      </header>
      <main class="grid">
    ${lib.concatMapStrings renderTile tiles}
      </main>
      <script src="status.js"></script>
    </body>
    </html>
  '';

  site = pkgs.runCommand "survival-kit-dashboard" { } ''
    mkdir $out
    cp ${page} $out/index.html
    cp ${./style.css} $out/style.css
    cp ${./status.js} $out/status.js
  '';
in
{
  options.survivalKit.dashboard.links = mkOption {
    type = types.attrsOf (
      types.submodule (
        { name, ... }:
        {
          options = {
            title = mkOption {
              type = types.str;
              default = name;
            };
            description = mkOption {
              type = types.str;
              default = "";
            };
            url = mkOption { type = types.str; };
            order = mkOption {
              type = types.int;
              default = 100;
            };
          };
        }
      )
    );
    default = { };
    description = "Dashboard tiles that are not services (e.g. the manual).";
  };

  config.survivalKit.web.dashboardRoot = site;
}
