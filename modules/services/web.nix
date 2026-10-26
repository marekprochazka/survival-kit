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
  # every vhost: HTTPS with the box's own certificate (modules/tls); plain http
  # answers 301 → https, so old links and typed names keep working
  tlsVhost = {
    forceSSL = true;
    sslCertificate = "${config.survivalKit.tls.dir}/deck.crt";
    sslCertificateKey = "${config.survivalKit.tls.dir}/deck.key";
  };

  entryType = types.submodule (
    { name, ... }:
    {
      options = {
        subdomain = mkOption {
          type = types.str;
          default = name;
          description = "Served at https://<subdomain>.<domain>.";
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

  names = lib.attrNames registry;
  subdomains = lib.mapAttrsToList (_: svc: svc.subdomain) registry;
  # keys used by more than one entry, as "key (entry, entry)" — keyOf: entry → string
  clashes =
    keyOf:
    lib.mapAttrsToList (key: users: "${key} (${lib.concatStringsSep ", " users})") (
      lib.filterAttrs (_: users: lib.length users > 1) (
        lib.groupBy' (users: name: users ++ [ name ]) [ ] (name: keyOf registry.${name}) names
      )
    );
  subdomainClashes = clashes (svc: lib.toLower svc.subdomain); # DNS ignores case
  portClashes = clashes (svc: toString svc.port);
  # safe for URLs, nginx config and /etc/hosts
  isSafe = s: builtins.match "[a-z0-9-]+" s != null;
  unsafeNames = lib.filter (name: !(isSafe name && isSafe registry.${name}.subdomain)) names;
  onNginxPorts = lib.filter (
    name:
    lib.elem registry.${name}.port [
      80
      443
    ]
  ) names;
in
{
  options.survivalKit = {
    web = {
      domain = mkOption {
        type = types.str;
        default = "deck";
        description = "Local domain: dashboard at https://<domain>, services at https://<sub>.<domain>.";
      };
      dashboardRoot = mkOption {
        type = types.path;
        default = pkgs.writeTextDir "index.html" "<h1>survival-kit</h1>";
        defaultText = lib.literalMD "a placeholder page";
        description = "Directory served at https://<domain> (set by the dashboard module).";
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
        assertion = subdomainClashes == [ ];
        message = "survivalKit.registry: duplicate subdomain(s): ${lib.concatStringsSep "; " subdomainClashes}";
      }
      {
        assertion = portClashes == [ ];
        message = "survivalKit.registry: duplicate port(s): ${lib.concatStringsSep "; " portClashes}";
      }
      {
        assertion = onNginxPorts == [ ];
        message = "survivalKit.registry: port 80/443 is nginx's own — used by: ${lib.concatStringsSep ", " onNginxPorts}";
      }
      {
        assertion = unsafeNames == [ ];
        message = "survivalKit.registry: names and subdomains may only use a-z, 0-9 and '-': ${lib.concatStringsSep ", " unsafeNames}";
      }
      {
        assertion = lib.all (s: s != "" && s != domain) subdomains;
        message = "survivalKit.registry: a subdomain is empty or equals the bare domain '${domain}'";
      }
    ];

    services.nginx = {
      enable = true;
      recommendedProxySettings = true;
      recommendedTlsSettings = true; # modern protocols/ciphers, session cache
      virtualHosts = {
        ${domain} = tlsVhost // {
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
        _: svc:
        lib.nameValuePair (fqdn svc) (
          tlsVhost
          // {
            locations."/" = {
              proxyPass = upstream svc;
              proxyWebsockets = true; # live updates (Vaultwarden sync, later Trilium, Jellyfin)
            };
          }
        )
      ) registry;
    };

    # the certificate must exist before nginx loads it. Requires: a re-issue (new
    # service → new name → the TLS unit restarts on switch) restarts nginx too.
    systemd.services.nginx = {
      after = [ "survival-kit-tls.service" ];
      requires = [ "survival-kit-tls.service" ];
    };

    # Local name resolution for the box itself; dnsmasq (AP-hub round) will
    # read the same registry for other devices.
    networking.hosts."127.0.0.1" = [ domain ] ++ lib.mapAttrsToList (_: fqdn) registry;
  };
}
