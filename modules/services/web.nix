# The registry consumer (ADR-0002 §6–7): every service registers one entry in
# survivalKit.registry; this module turns the registry into nginx vhosts,
# /etc/hosts lines, same-origin health endpoints, and build-time sanity checks.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  inherit (lib) mkOption types;
  inherit (config.survivalKit) registry web;
  inherit (web) domain;

  fqdn = svc: "${svc.subdomain}.${domain}";
  upstream = svc: "http://127.0.0.1:${toString svc.port}";

  entryType = types.submodule (
    { name, ... }:
    {
      options = {
        subdomain = mkOption {
          type = types.str;
          default = name;
          description = "Served at http://<subdomain>.<domain>.";
        };
        port = mkOption {
          type = types.port;
          description = "Port the service listens on (127.0.0.1 only).";
        };
        title = mkOption {
          type = types.str;
          default = name;
          description = "Dashboard tile title.";
        };
        description = mkOption {
          type = types.str;
          default = "";
          description = "Dashboard tile description.";
        };
        order = mkOption {
          type = types.int;
          default = 100;
          description = "Dashboard position (lower first; ties sorted by name).";
        };
        healthPath = mkOption {
          type = types.str;
          default = "/";
          description = "Path probed by the dashboard via /health/<name>.";
        };
      };
    }
  );

  duplicates = xs: lib.unique (lib.filter (x: lib.count (y: y == x) xs > 1) xs);
  subdomains = lib.mapAttrsToList (_: svc: svc.subdomain) registry;
  ports = lib.mapAttrsToList (_: svc: svc.port) registry;
in
{
  options.survivalKit = {
    web = {
      domain = mkOption {
        type = types.str;
        default = "deck";
        description = "Local domain: dashboard at http://<domain>, services at http://<sub>.<domain>.";
      };
      dashboardRoot = mkOption {
        type = types.path;
        default = pkgs.writeTextDir "index.html" "<h1>survival-kit</h1>";
        defaultText = lib.literalMD "a placeholder page";
        description = "Directory served at http://<domain> (set by the dashboard module).";
      };
    };
    registry = mkOption {
      type = types.attrsOf entryType;
      default = { };
      description = "Web services, one entry each; set by the service modules.";
    };
  };

  config = {
    assertions = [
      {
        assertion = duplicates subdomains == [ ];
        message = "survivalKit.registry: duplicate subdomain(s): ${toString (duplicates subdomains)}";
      }
      {
        assertion = duplicates ports == [ ];
        message = "survivalKit.registry: duplicate port(s): ${toString (duplicates ports)}";
      }
      {
        assertion = lib.all (s: s != "" && s != domain) subdomains;
        message = "survivalKit.registry: a subdomain is empty or equals the bare domain '${domain}'";
      }
    ];

    services.nginx = {
      enable = true;
      recommendedProxySettings = true;
      virtualHosts = {
        ${domain} = {
          default = true; # catch-all: access by IP lands on the dashboard
          serverAliases = [ "${config.networking.hostName}.local" ];
          root = web.dashboardRoot;
          # same-origin health probes for the dashboard's JS (no CORS)
          locations = lib.mapAttrs' (
            name: svc:
            lib.nameValuePair "= /health/${name}" {
              proxyPass = "${upstream svc}${svc.healthPath}";
            }
          ) registry;
        };
      }
      // lib.mapAttrs' (
        _: svc: lib.nameValuePair (fqdn svc) { locations."/".proxyPass = upstream svc; }
      ) registry;
    };

    # Local name resolution for the box itself; dnsmasq (AP-hub round) will
    # read the same registry for other devices.
    networking.hosts."127.0.0.1" = [ domain ] ++ lib.mapAttrsToList (_: fqdn) registry;
  };
}
