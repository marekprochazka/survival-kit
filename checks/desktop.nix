# Layer 3 — desktop VM test (local only): autologin into XFCE, panel/apps,
# Firefox on the dashboard (maximized). Saves a screenshot in the output.
{
  pkgs,
  self,
  inputs,
  ...
}:
pkgs.testers.runNixOSTest {
  name = "desktop";
  node.specialArgs = { inherit inputs self; };
  nodes.machine = {
    imports = [ (import ./host-node.nix { inherit inputs; }) ];
    environment.systemPackages = [ pkgs.xprop ]; # test-only: read window state
  };
  testScript = ''
    uid = ""  # set after login; str (not None) so the driver's type check passes

    def as_hera(cmd):
        return machine.succeed(
            "su - hera -c 'DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"
            + uid + "/bus " + cmd + "'"
        ).strip()

    with subtest("autologin into XFCE, no login prompt"):
        machine.wait_for_x()
        machine.wait_for_file("/home/hera/.Xauthority")
        machine.succeed("xauth merge /home/hera/.Xauthority")
        uid = machine.succeed("id -u hera").strip()
        # -f (full cmdline): nixpkgs wraps XFCE binaries, so the process name is
        # ".xfce4-session-wrapped" and -x never matches; -u hera skips our own shell
        machine.wait_until_succeeds("pgrep -u hera -f xfce4-session", timeout=120)
        machine.wait_until_succeeds("pgrep -u hera -f xfce4-panel", timeout=120)
        machine.wait_for_window("xfce4-panel")

    with subtest("no screen locker installed"):
        machine.fail("test -e /run/current-system/sw/bin/xfce4-screensaver")

    with subtest("rescue TTY still shows a login prompt"):
        # consoles start on demand (Ctrl+Alt+F2 does this); start one directly so
        # the X display keeps focus for the later subtests
        machine.succeed("systemctl start getty@tty2.service")
        machine.wait_until_tty_matches("2", "login: ", timeout=60)

    with subtest("xfconf defaults from /etc/xdg are in effect"):
        machine.wait_until_succeeds(
            "su - hera -c 'DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"
            + uid + "/bus xfconf-query -c xfce4-panel -p /plugins -l -v' | grep -q systemload",
            timeout=60,
        )
        assert as_hera("xfconf-query -c xfwm4 -p /general/use_compositing") == "false"
        assert as_hera(
            "xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/lock-screen-suspend-hibernate"
        ) == "false"
  '';
}
