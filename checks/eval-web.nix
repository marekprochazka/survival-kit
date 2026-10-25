# Layer 2 — eval assertions: registry → nginx vhosts, /etc/hosts, health
# endpoints, and the build-time safety assertions (incl. negative cases).
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  base = self.nixosConfigurations.survival-kit;
  withModules = modules: (base.extendModules { inherit modules; }).config;
  failing = cfg: map (a: a.message) (lib.filter (a: !a.assertion) cfg.assertions);
  hasFailure = cfg: text: lib.any (lib.hasInfix text) (failing cfg);

  demo = withModules [
    {
      survivalKit.registry.demo = {
        port = 9999;
        title = "Demo";
      };
    }
  ];
  vhosts = demo.services.nginx.virtualHosts;
  hosts = demo.networking.hosts."127.0.0.1";

  dupSubdomain = withModules [
    {
      survivalKit.registry = {
        a = {
          subdomain = "same";
          port = 9001;
        };
        b = {
          subdomain = "same";
          port = 9002;
        };
      };
    }
  ];
  dupPort = withModules [
    {
      survivalKit.registry = {
        a.port = 9003;
        b.port = 9003;
      };
    }
  ];
  bareDomain = withModules [
    {
      survivalKit.registry.x = {
        subdomain = "deck";
        port = 9004;
      };
    }
  ];
in
assert lib.assertMsg (vhosts ? "demo.deck") "registry entry should create vhost demo.deck";
assert lib.assertMsg (
  vhosts."demo.deck".locations."/".proxyPass == "http://127.0.0.1:9999"
) "demo.deck should proxy to 127.0.0.1:9999";
assert lib.assertMsg vhosts.deck.default "deck must be the default (catch-all) vhost";
assert lib.assertMsg (lib.elem "survival-kit.local" vhosts.deck.serverAliases)
  "deck vhost should answer to survival-kit.local";
assert lib.assertMsg (
  vhosts.deck.locations."= /health/demo".proxyPass == "http://127.0.0.1:9999/"
) "health endpoint should proxy to the service's healthPath";
assert lib.assertMsg (
  lib.elem "deck" hosts && lib.elem "demo.deck" hosts
) "/etc/hosts should map deck and demo.deck to 127.0.0.1";
assert lib.assertMsg (
  failing demo == [ ]
) "a valid registry must not trip assertions: ${toString (failing demo)}";
assert lib.assertMsg (hasFailure dupSubdomain "duplicate subdomain")
  "duplicate subdomains must fail the build";
assert lib.assertMsg (hasFailure dupPort "duplicate port") "duplicate ports must fail the build";
assert lib.assertMsg (hasFailure bareDomain "bare domain")
  "subdomain equal to the domain must fail the build";
assert lib.assertMsg (
  base.config.services.nginx.virtualHosts."wiki.deck".locations."/".proxyPass
  == "http://127.0.0.1:8080"
) "wiki.deck should proxy to Kiwix on 127.0.0.1:8080";
assert lib.assertMsg (
  base.config.services.kiwix-serve.address == "127.0.0.1"
) "kiwix-serve must listen on 127.0.0.1 only";
pkgs.runCommand "eval-web" { } "touch $out"
