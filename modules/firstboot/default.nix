# First-boot provisioning (ADR-0001 §7): a one-shot prompt on tty1, before the
# desktop, sets the display name and password of the fixed account. Runs until
# it has succeeded once (marker file); the desktop never waits on a failure.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.survivalKit.firstBoot;
  marker = "/var/lib/survival-kit/firstboot-done";
  namefile = "/var/lib/survival-kit/display-name"; # written by firstboot.sh
  prompt = pkgs.writeShellApplication {
    name = "survival-kit-firstboot";
    runtimeInputs = with pkgs; [
      coreutils
      shadow # usermod, chpasswd
    ];
    text = ''
      FIRSTBOOT_USER=${lib.escapeShellArg cfg.user}
    ''
    + builtins.readFile ./firstboot.sh;
  };
in
{
  options.survivalKit.firstBoot = {
    enable = lib.mkEnableOption "the first-boot name/password prompt" // {
      default = true;
    };
    user = lib.mkOption {
      type = lib.types.str;
      default = config.survivalKit.desktop.autoLoginUser;
      defaultText = lib.literalExpression "config.survivalKit.desktop.autoLoginUser";
      description = "Account whose display name and password are set at first boot.";
    };
  };

  config = lib.mkIf cfg.enable {
    # Quiet console: otherwise "[ OK ] Started …" lines print into the prompt on
    # tty1 (services still starting). Failures are still shown.
    boot.kernelParams = [
      "quiet"
      "systemd.show_status=error"
    ];
    boot.consoleLogLevel = lib.mkDefault 3; # kernel: errors only (tests raise it)

    # NixOS rewrites /etc/passwd from the config at every activation (boot,
    # rebuild), which would wipe the name set at first boot — re-apply it.
    system.activationScripts.survival-kit-display-name = {
      deps = [ "users" ];
      text = ''
        if [ -s ${namefile} ]; then
          ${pkgs.shadow}/bin/usermod -c "$(cat ${namefile})" ${lib.escapeShellArg cfg.user} || true
        fi
      '';
    };

    systemd.services.survival-kit-firstboot = {
      description = "survival-kit first boot: set name and password";
      wantedBy = [
        "multi-user.target"
        "display-manager.service" # Wants: the desktop waits, but never on a failure
      ];
      before = [
        "display-manager.service"
        "getty@tty1.service"
      ];
      conflicts = [ "getty@tty1.service" ];
      after = [
        "systemd-user-sessions.service"
        "systemd-vconsole-setup.service"
      ];
      unitConfig.ConditionPathExists = "!${marker}";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = lib.getExe prompt;
        StandardInput = "tty-force";
        StandardOutput = "tty";
        StandardError = "tty";
        TTYPath = "/dev/tty1";
        TTYReset = true;
        TTYVHangup = true;
      };
    };
  };
}
