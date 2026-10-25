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

  dashboardUrl = "http://${config.survivalKit.web.domain}";
  openDashboard = pkgs.writeShellApplication {
    name = "survival-kit-open-dashboard";
    runtimeInputs = with pkgs; [
      coreutils
      curl
      gnugrep
      wmctrl
    ]; # firefox comes from the session PATH (the policy-wrapped one)
    text = builtins.readFile ./open-dashboard.sh;
  };
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
    programs.firefox = {
      enable = true;
      policies = {
        Homepage = {
          URL = dashboardUrl;
          StartPage = "homepage";
        };
        DisableTelemetry = true;
        DisableFirefoxStudies = true;
        DisablePocket = true;
        DontCheckDefaultBrowser = true;
        OverrideFirstRunPage = "";
        OverridePostUpdatePage = "";
        FirefoxHome = {
          SponsoredTopSites = false;
          Pocket = false;
          SponsoredPocket = false;
          Stories = false;
          SponsoredStories = false;
        };
        UserMessaging = {
          SkipOnboarding = true;
          ExtensionRecommendations = false;
          FeatureRecommendations = false;
          MoreFromMozilla = false;
        };
      };
      # without this, typing "wiki.deck" in the address bar runs a web search
      preferences."browser.fixup.domainsuffixwhitelist.${config.survivalKit.web.domain}" = true;
    };

    environment.etc = xfconfDefaults // {
      "xdg/autostart/survival-kit-dashboard.desktop".text = ''
        [Desktop Entry]
        Type=Application
        Name=survival-kit dashboard
        Comment=Open the dashboard in Firefox at login
        Exec=${lib.getExe openDashboard} ${dashboardUrl}
        OnlyShowIn=XFCE;
      '';
    };
  };
}
