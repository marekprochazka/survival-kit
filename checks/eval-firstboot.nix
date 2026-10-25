# Layer 2 — eval assertions: account deck (locked until first boot), first-boot
# service wiring.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  cfg = self.nixosConfigurations.survival-kit.config;
  deck = cfg.users.users.deck;
  svc = cfg.systemd.services.survival-kit-firstboot;
in
assert lib.assertMsg (
  deck.isNormalUser && lib.elem "wheel" deck.extraGroups
) "deck must be a normal sudo-capable user";
assert lib.assertMsg (
  deck.initialHashedPassword == "!"
) "deck's password must be locked until first boot";
assert lib.assertMsg (!(cfg.users.users ? hera)) "dev user hera must be gone";
assert lib.assertMsg (
  cfg.services.displayManager.autoLogin.user == "deck"
) "autologin must use deck";
assert lib.assertMsg cfg.users.mutableUsers
  "users must stay mutable (runtime password survives rebuilds)";
assert lib.assertMsg (lib.elem "display-manager.service" svc.before)
  "first boot must run before the desktop";
assert lib.assertMsg (
  svc.unitConfig.ConditionPathExists == "!/var/lib/survival-kit/firstboot-done"
) "first boot must run only until its marker exists";
pkgs.runCommand "eval-firstboot" { } "touch $out"
