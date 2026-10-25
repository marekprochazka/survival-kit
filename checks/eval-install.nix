# Layer 2 — eval assertions for installs: selection → bootloader target,
# hardware baseline, offline flake inputs.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  base = self.nixosConfigurations.survival-kit;
  cfg = base.config;
  sda = (base.extendModules { modules = [ { survivalKit.disk.device = "/dev/sda"; } ]; }).config;
  deps = map toString cfg.system.extraDependencies;
in
assert lib.assertMsg (
  sda.boot.loader.grub.devices == [ "/dev/sda" ]
) "the selected disk must become GRUB's install target";
assert lib.assertMsg cfg.hardware.enableAllHardware
  "installs need the broad driver set (same as the installer ISO)";
assert lib.assertMsg cfg.hardware.enableRedistributableFirmware
  "installs need redistributable firmware (Wi-Fi etc.)";
assert lib.assertMsg (lib.all (i: lib.elem (toString i) deps) [
  self.inputs.nixpkgs
  self.inputs.disko
]) "flake input sources must be on the system so /etc/nixos rebuilds offline";
pkgs.runCommand "eval-install" { } "touch $out"
