# Layer 2 — eval assertions: the box's certificate authority service.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  cfg = self.nixosConfigurations.survival-kit.config;
  svc = cfg.systemd.services.survival-kit-tls;
in
assert lib.assertMsg cfg.survivalKit.tls.enable "TLS must be on by default";
assert lib.assertMsg (
  cfg.survivalKit.tls.dir == "/var/lib/survival-kit/tls"
) "certificates live in /var/lib/survival-kit/tls (runtime, never in the Nix store)";
assert lib.assertMsg (lib.elem "nginx.service" svc.before)
  "certificates must exist before nginx starts";
assert lib.assertMsg (lib.elem "multi-user.target" svc.wantedBy)
  "the TLS service runs at every boot";
pkgs.runCommand "eval-tls" { } "touch $out"
