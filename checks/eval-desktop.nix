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
assert lib.assertMsg (lib.all
  (f: cfg.environment.etc ? "xdg/xfce4/xfconf/xfce-perchannel-xml/${f}.xml")
  [
    "xfce4-panel"
    "xfwm4"
    "xfce4-power-manager"
  ]
) "xfconf defaults must be installed under /etc/xdg";
assert lib.assertMsg cfg.programs.firefox.enable "firefox must be enabled";
assert lib.assertMsg (
  cfg.programs.firefox.policies.Homepage.URL == "http://deck"
) "firefox homepage must be the dashboard";
assert lib.assertMsg (
  cfg.programs.firefox.preferences."browser.fixup.domainsuffixwhitelist.deck" == true
) "firefox must treat .deck as a real domain (else typing wiki.deck searches the web)";
assert lib.assertMsg (
  cfg.environment.etc ? "xdg/autostart/survival-kit-dashboard.desktop"
) "dashboard autostart entry must exist";
pkgs.runCommand "eval-desktop" { } "touch $out"
