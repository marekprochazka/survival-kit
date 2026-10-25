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
    };
  testScript = ''
    with subtest("prompt on tty1 before the desktop"):
        machine.wait_until_tty_matches("1", "Your name", timeout=120)
        machine.fail("systemctl is-active display-manager.service")

    with subtest("name, a mismatched password pair, then a matching pair"):
        machine.send_chars("Test Person\n")
        machine.wait_until_tty_matches("1", "Choose a password")
        machine.send_chars("first-secret\n")
        machine.wait_until_tty_matches("1", "Repeat")
        machine.send_chars("different\n")
        machine.wait_until_tty_matches("1", "not matching")
        machine.send_chars("s3cret-pass\n")
        machine.sleep(1)
        machine.send_chars("s3cret-pass\n")

    with subtest("desktop starts, logged in as deck with the display name"):
        machine.wait_for_unit("display-manager.service")
        machine.wait_until_succeeds("pgrep -u deck -f xfce4-session", timeout=120)
        assert "Test Person" in machine.succeed("getent passwd deck")
        machine.succeed("test -e /var/lib/survival-kit/firstboot-done")

    with subtest("the password works: real console login on tty2"):
        machine.succeed("systemctl start getty@tty2.service")
        machine.succeed("chvt 2")
        machine.wait_until_tty_matches("2", "login: ", timeout=60)
        machine.send_chars("deck\n")
        machine.wait_until_tty_matches("2", "Password: ")
        machine.send_chars("s3cret-pass\n")
        machine.wait_until_succeeds("pgrep -u deck -t tty2", timeout=30)

    with subtest("after a reboot there is no prompt"):
        machine.shutdown()
        machine.start()
        machine.wait_until_succeeds("pgrep -u deck -f xfce4-session", timeout=180)
        assert "ConditionResult=no" in machine.succeed(
            "systemctl show survival-kit-firstboot.service -p ConditionResult"
        )
        # NixOS rewrites /etc/passwd at every boot — the display name must survive
        assert "Test Person" in machine.succeed("getent passwd deck"), "display name lost on reboot"
  '';
}
