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

    def as_deck(cmd):
        return machine.succeed(
            "su - deck -c 'DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"
            + uid + "/bus " + cmd + "'"
        ).strip()

    with subtest("autologin into XFCE, no login prompt"):
        machine.wait_for_x()
        machine.wait_for_file("/home/deck/.Xauthority")
        machine.succeed("xauth merge /home/deck/.Xauthority")
        uid = machine.succeed("id -u deck").strip()
        # -f (full cmdline): nixpkgs wraps XFCE binaries, so the process name is
        # ".xfce4-session-wrapped" and -x never matches; -u deck skips our own shell
        machine.wait_until_succeeds("pgrep -u deck -f xfce4-session", timeout=120)
        machine.wait_until_succeeds("pgrep -u deck -f xfce4-panel", timeout=120)
        machine.wait_for_window("xfce4-panel")

    with subtest("apps and power settings are in place"):
        machine.succeed("command -v papers btop")
        # our power-manager defaults are in effect (xset can't tell: 600 s is also X's
        # built-in default); xfconf-query fails if a property was never set
        assert as_deck("xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/blank-on-ac") == "10"
        assert as_deck("xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/dpms-on-ac-off") == "15"

    with subtest("no screen locker installed"):
        machine.fail("test -e /run/current-system/sw/bin/xfce4-screensaver")

    with subtest("rescue TTY still shows a login prompt"):
        # consoles start on demand (Ctrl+Alt+F2 does this); start one directly so
        # the X display keeps focus for the later subtests
        machine.succeed("systemctl start getty@tty2.service")
        machine.wait_until_tty_matches("2", "login: ", timeout=60)

    with subtest("xfconf defaults from /etc/xdg are in effect"):
        machine.wait_until_succeeds(
            "su - deck -c 'DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"
            + uid + "/bus xfconf-query -c xfce4-panel -p /plugins -l -v' | grep -q systemload",
            timeout=60,
        )
        assert as_deck("xfconf-query -c xfwm4 -p /general/use_compositing") == "false"
        assert as_deck(
            "xfconf-query -c xfce4-power-manager -p /xfce4-power-manager/lock-screen-suspend-hibernate"
        ) == "false"

    with subtest("Firefox opens the dashboard, maximized"):
        machine.wait_for_window("survival-kit")  # dashboard <title> = hostname
        # select by WM_CLASS: every wmctrl line also contains the hostname "survival-kit"
        # retried: the window can show up in X before the window manager lists it
        machine.wait_until_succeeds("DISPLAY=:0 wmctrl -l -x | grep -q 'Navigator.firefox'", timeout=60)
        wid = machine.succeed("DISPLAY=:0 wmctrl -l -x | grep 'Navigator.firefox' | head -1 | cut -d' ' -f1").strip()
        machine.wait_until_succeeds(
            f"DISPLAY=:0 xprop -id {wid} _NET_WM_STATE | grep -q _NET_WM_STATE_MAXIMIZED_VERT",
            timeout=60,
        )
        machine.succeed(f"DISPLAY=:0 xprop -id {wid} _NET_WM_STATE | grep -q _NET_WM_STATE_MAXIMIZED_HORZ")
        machine.sleep(3)  # let the page paint before the screenshot
        machine.screenshot("desktop")

    # Firefox's selected tab shows the dashboard (window title = page title)
    DASHBOARD_TAB = "DISPLAY=:0 wmctrl -l -x | grep Navigator.firefox | grep -q 'survival-kit — Mozilla Firefox'"

    def restart_session():
        # the graphical half of a reboot: LightDM autologins again, autostart runs
        machine.succeed("systemctl restart display-manager.service")
        machine.wait_until_succeeds("pgrep -u deck -f xfce4-session", timeout=120)
        machine.wait_for_file("/home/deck/.Xauthority")
        machine.sleep(2)
        machine.succeed("xauth merge /home/deck/.Xauthority")

    with subtest("after a crash (power loss) Firefox starts on the dashboard, not old pages"):
        # open a wiki page in the running Firefox (remote open goes via the session bus)
        machine.succeed(
            "su - deck -c 'DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/"
            + uid + "/bus firefox http://wiki.deck/ >&2 &'"
        )
        machine.wait_until_succeeds(
            "DISPLAY=:0 wmctrl -l -x | grep Navigator.firefox | grep -v 'survival-kit — Mozilla Firefox'",
            timeout=60,
        )
        machine.sleep(20)  # let session store save the wiki tab (15 s interval)
        machine.succeed("pkill -9 -u deck -f firefox")
        restart_session()
        machine.wait_until_succeeds(DASHBOARD_TAB, timeout=90)

    with subtest("dashboard still opens when nginx comes up late (slow first boot)"):
        machine.succeed("pkill -u deck -f firefox || true")
        machine.wait_until_fails("pgrep -u deck -f firefox", timeout=60)
        machine.succeed("systemctl stop nginx.service")
        restart_session()
        machine.sleep(40)  # slower than the helper's original 30 s wait
        machine.succeed("systemctl start nginx.service")
        machine.wait_until_succeeds(DASHBOARD_TAB, timeout=120)
  '';
}
