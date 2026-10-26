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
  # build outputs of a prebuilt variant (representative device, see modules/installer)
  variantBuild =
    { encrypt, profile }:
    (base.extendModules {
      modules = [
        {
          survivalKit.disk = {
            device = "/dev/sda";
            inherit encrypt;
          };
          survivalKit.profile = profile;
        }
      ];
    }).config.system.build;
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
assert lib.assertMsg
  (lib.all
    (
      v:
      let
        b = variantBuild v;
      in
      lib.all (d: lib.elem (toString d) installerDeps) [
        b.toplevel
        b.destroyFormatMount
        b.toplevel.inputDerivation # build inputs → any disk name installs offline
      ]
    )
    (
      lib.cartesianProduct {
        encrypt = [
          false
          true
        ];
        profile = [
          "lite"
          "full"
        ];
      }
    )
  )
  "installer must carry prebuilt systems (profile × encryption) + build inputs for offline installs";
assert lib.assertMsg (lib.hasInfix ''survivalKit.profile = "$profile";'' (
  builtins.readFile ../pkgs/survival-kit-install.sh
)) "the installer must write the chosen profile into selection.nix";
assert lib.assertMsg (lib.hasInfix "/etc/nixos" (
  builtins.toJSON cfg.programs.git.config
)) "git must trust the root-owned /etc/nixos repo (safe.directory) so users can read it";
# building this also builds the installer package (shellcheck) and runs --help
pkgs.runCommand "eval-install" { } "cat ${helpRuns} > /dev/null; touch $out"
