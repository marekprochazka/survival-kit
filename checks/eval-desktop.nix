# Layer 2 — eval assertions: desktop session, autologin, rescue TTYs, no locker.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  cfg = self.nixosConfigurations.survival-kit.config;
  dm = cfg.services.displayManager;
in
assert lib.assertMsg (
  dm.autoLogin.enable && dm.autoLogin.user == "hera"
) "desktop autologin must log in hera";
assert lib.assertMsg (dm.defaultSession == "xfce") "default session must be xfce";
assert lib.assertMsg (
  cfg.services.getty.autologinUser == null
) "TTYs must keep a login prompt (no getty autologin)";
assert lib.assertMsg (
  !cfg.services.xserver.desktopManager.xfce.enableScreensaver
) "no screen locker (user decision: no auto-lock)";
pkgs.runCommand "eval-desktop" { } "touch $out"
