# Layer 2 — eval assertions for the installer ISO (evaluated, not built).
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  iso = self.nixosConfigurations.installer.config;
  target =
    toString
      (self.nixosConfigurations.survival-kit.extendModules {
        modules = [
          {
            survivalKit.disk = {
              device = "/dev/sda";
              encrypt = false;
            };
          }
        ];
      }).config.system.build.toplevel;
in
assert lib.assertMsg iso.survivalKit.installer.enable "ISO must include the installer";
assert lib.assertMsg (
  iso.isoImage.makeBiosBootable && iso.isoImage.makeEfiBootable && iso.isoImage.makeUsbBootable
) "ISO must boot via BIOS, UEFI and from USB";
assert lib.assertMsg (lib.any (
  p: (p.name or "") == "survival-kit-install"
) iso.environment.systemPackages) "survival-kit-install must be on the ISO";
assert lib.assertMsg (lib.elem target (
  map toString iso.system.extraDependencies
)) "ISO must carry the prebuilt target system (offline install)";
assert lib.assertMsg (lib.hasInfix "survival-kit-install" iso.programs.bash.loginShellInit)
  "ISO must start the installer on tty1";
pkgs.runCommand "eval-iso" { } "touch $out"
