# Desktop (ADR-0002 §1–3): XFCE on X11, autologin straight into the session,
# no screen locker. Gated so a headless variant can leave it out.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.desktop;

  # every file in ./xfconf → /etc/xdg/xfce4/xfconf/xfce-perchannel-xml/<file>
  # (system-wide defaults; a user's own changes in ~/.config take precedence)
  xfconfDefaults = lib.mapAttrs' (
    file: _:
    lib.nameValuePair "xdg/xfce4/xfconf/xfce-perchannel-xml/${file}" { source = ./xfconf + "/${file}"; }
  ) (builtins.readDir ./xfconf);
in
{
  options.survivalKit.desktop = {
    enable = lib.mkEnableOption "the XFCE desktop with autologin";
    autoLoginUser = lib.mkOption {
      type = lib.types.str;
      description = "User logged in automatically at boot (no password prompt).";
    };
  };

  config = lib.mkIf cfg.enable {
    services.xserver = {
      enable = true;
      xkb.layout = "us";
      displayManager.lightdm.enable = true;
      desktopManager.xfce = {
        enable = true;
        enableScreensaver = false; # user decision: no auto-lock (LUKS covers data at rest)
      };
    };
    services.displayManager = {
      autoLogin = {
        enable = true;
        user = cfg.autoLoginUser;
      };
      defaultSession = "xfce";
    };

    environment.systemPackages = with pkgs; [
      papers # PDF/document viewer
      btop # terminal system monitor
      xfce4-systemload-plugin # panel CPU/RAM bars
      wmctrl # used by the dashboard autostart helper
    ];
    environment.etc = xfconfDefaults;
  };
}
