# Layer 2 — eval assertions for installs: selection → bootloader target,
# hardware baseline, offline flake inputs.
{ pkgs, self, ... }:
let
  inherit (pkgs) lib;
  base = self.nixosConfigurations.survival-kit;
  cfg = base.config;
  sda = (base.extendModules { modules = [ { survivalKit.disk.device = "/dev/sda"; } ]; }).config;
  deps = map toString cfg.system.extraDependencies;

  installerPkg = self.packages.x86_64-linux.survival-kit-install;
  helpRuns = pkgs.runCommand "installer-help" { } ''
    ${lib.getExe installerPkg} --help > $out
  '';
  installerSys = self.inputs.nixpkgs.lib.nixosSystem {
    system = "x86_64-linux";
    specialArgs = {
      inherit (self) inputs;
      inherit self;
    };
    modules = [
      ../modules/installer
      {
        survivalKit.installer.enable = true;
        fileSystems."/".device = "none";
        boot.loader.grub.enable = false;
        system.stateVersion = "26.05";
      }
    ];
  };
  installerDeps = map toString installerSys.config.system.extraDependencies;
  variant =
    disk:
    toString
      (base.extendModules { modules = [ { survivalKit.disk = disk; } ]; }).config.system.build.toplevel;
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
assert lib.assertMsg (lib.all (d: lib.elem (variant d) installerDeps) [
  {
    device = "/dev/sda";
    encrypt = false;
  }
  {
    device = "/dev/nvme0n1";
    encrypt = true;
  }
]) "installer must carry prebuilt target systems for offline installs";
# building this also builds the installer package (shellcheck) and runs --help
pkgs.runCommand "eval-install" { } "cat ${helpRuns} > /dev/null; touch $out"
