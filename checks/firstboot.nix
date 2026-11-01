# Layer 3 — first-boot VM test (local only): the tty1 prompt sets display name +
# password before the desktop starts, then never comes back.
{
  pkgs,
  self,
  inputs,
  ...
}:
pkgs.testers.runNixOSTest {
  name = "firstboot";
  node.specialArgs = { inherit inputs self; };
  nodes.machine =
    { lib, ... }:
    {
      imports = [ (import ./host-node.nix { inherit inputs; }) ];
      survivalKit.firstBoot.enable = lib.mkForce true;
      # Media (Jellyfin) refuses to start with less than 2 GiB free (the default disk is 1 GB)
      virtualisation.diskSize = 4096;
    };
  testScript = ''
    with subtest("prompt on tty1 before the desktop"):
        machine.wait_until_tty_matches("1", "Your name", timeout=120)
        # QEMU's extra input devices re-run console setup on tty1, which can drop
        # keys typed meanwhile: let device setup settle before typing
        machine.succeed("udevadm settle")
        machine.fail("systemctl is-active display-manager.service")

    with subtest("name, a mismatched password pair, then a matching pair"):
        machine.send_chars("Test Person\n")
        machine.wait_until_tty_matches("1", "Choose a password")
        machine.send_chars("first-secret\n")
        machine.wait_until_tty_matches("1", "Repeat")
        machine.send_chars("different\n")
        machine.wait_until_tty_matches("1", "not matching")
        # wait for each (repeated) prompt before typing — no blind sleeps
        machine.wait_until_tty_matches("1", "(?s)Choose a password.*Choose a password")
        machine.send_chars("s3cret-pass\n")
        machine.wait_until_tty_matches("1", "(?s)Repeat.*Repeat")
        machine.send_chars("s3cret-pass\n")

    with subtest("desktop starts, logged in as deck with the display name"):
        try:
            machine.wait_for_unit("display-manager.service", timeout=600)
        except Exception:
            print("tty1 was showing:\n" + machine.get_tty_text("1"))  # e.g. a Media note
            raise
        machine.wait_until_succeeds("pgrep -u deck -f xfce4-session", timeout=120)
        assert "Test Person" in machine.succeed("getent passwd deck")
        machine.succeed("test -e /var/lib/survival-kit/firstboot-done")

    with subtest("Media's owner has the same name and password"):
        machine.succeed("test -s /var/lib/survival-kit/media/api-key")
        machine.succeed(
            "curl -sf -X POST -H 'Content-Type: application/json'"
            " -H 'Authorization: MediaBrowser Client=\"t\", Device=\"vm\", DeviceId=\"fb\", Version=\"1\"'"
            " --data-binary '{\"Username\": \"Test Person\", \"Pw\": \"s3cret-pass\"}'"
            " http://127.0.0.1:8096/Users/AuthenticateByName"
        )

    with subtest("the password works: real console login on tty2"):
        machine.succeed("systemctl start getty@tty2.service")
        machine.succeed("chvt 2")
        machine.wait_until_tty_matches("2", "login: ", timeout=60)
        machine.send_chars("deck\n")
        machine.wait_until_tty_matches("2", "Password: ")
        machine.send_chars("s3cret-pass\n")
        machine.wait_until_succeeds("pgrep -u deck -t tty2", timeout=30)

    with subtest("after a reboot there is no prompt"):
        ca_before = machine.succeed("sha256sum /var/lib/survival-kit/tls/ca.crt")
        machine.shutdown()
        machine.start()
        machine.wait_until_succeeds("pgrep -u deck -f xfce4-session", timeout=180)
        assert "ConditionResult=no" in machine.succeed(
            "systemctl show survival-kit-firstboot.service -p ConditionResult"
        )
        # NixOS rewrites /etc/passwd at every boot — the display name must survive
        assert "Test Person" in machine.succeed("getent passwd deck"), "display name lost on reboot"
        # the box's CA is created once and never replaced (trust would break)
        assert machine.succeed("sha256sum /var/lib/survival-kit/tls/ca.crt") == ca_before, "CA changed on reboot"
  '';
}
