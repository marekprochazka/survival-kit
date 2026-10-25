# Layer 3 — NixOS VM test (local only): boot the real host config, expect zero
# failed units. VM tests swap in their own disk, so the disko layout is NOT
# tested here — that's eval-disk (layer 2) and the manual install test.
{
  pkgs,
  self,
  inputs,
  ...
}:
pkgs.testers.runNixOSTest {
  name = "boot";
  node.specialArgs = { inherit inputs self; };
  nodes.machine.imports = [
    ../hosts/survival-kit
    inputs.disko.nixosModules.disko
  ];
  testScript = ''
    machine.wait_for_unit("multi-user.target")
    # 'running' (exit 0) only if no unit failed; 'degraded' exits non-zero
    machine.succeed("systemctl is-system-running --wait")
  '';
}
