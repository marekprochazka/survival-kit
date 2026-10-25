# All automated tests (ADR-0003). Each attribute is one check:
#   nix build .#checks.x86_64-linux.<name>   → run one
#   nix flake check                          → run all
{
  pkgs,
  self,
  inputs,
}:
let
  inherit (pkgs) lib;
in
{
  # Layer 1 — static: formatting + lints over the flake's source tree.
  lint =
    pkgs.runCommand "lint"
      {
        nativeBuildInputs = with pkgs; [
          nixfmt
          statix
          deadnix
        ];
      }
      ''
        cd ${self}
        find . -name '*.nix' -print0 | xargs -0 nixfmt --check
        statix check .
        deadnix --fail .
        touch $out
      '';

  # Layer 2 — eval assertions: facts about the config, no build or boot.
  eval-disk =
    let
      withEncrypt =
        encrypt:
        (self.nixosConfigurations.survival-kit.extendModules {
          modules = [ { survivalKit.disk.encrypt = encrypt; } ];
        }).config;
      plain = withEncrypt false;
      luks = withEncrypt true;
    in
    assert lib.assertMsg (
      plain.fileSystems."/".device == "/dev/disk/by-partlabel/disk-main-root"
    ) "plain: root should mount from the disko partlabel";
    assert lib.assertMsg (plain.boot.initrd.luks.devices == { }) "plain: expected no LUKS devices";
    assert lib.assertMsg (
      luks.fileSystems."/".device == "/dev/mapper/cryptroot"
    ) "luks: root should mount from /dev/mapper/cryptroot";
    assert lib.assertMsg (luks.boot.initrd.luks.devices ? cryptroot) "luks: expected cryptroot device";
    pkgs.runCommand "eval-disk" { } "touch $out";

  # Layer 3 — NixOS VM test (local only): boot the real host config, expect zero
  # failed units. Note: VM tests swap in their own disk, so the disko layout is
  # NOT tested here — that's eval-disk (layer 2) and the manual install test.
  boot = pkgs.testers.runNixOSTest {
    name = "boot";
    node.specialArgs = { inherit inputs self; };
    nodes.machine = {
      imports = [
        ../hosts/survival-kit
        inputs.disko.nixosModules.disko
      ];
    };
    testScript = ''
      machine.wait_for_unit("multi-user.target")
      # 'running' (exit 0) only if no unit failed; 'degraded' exits non-zero
      machine.succeed("systemctl is-system-running --wait")
    '';
  };
}
