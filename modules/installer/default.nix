# Installer (ADR-0001 step 4b): the survival-kit-install command plus everything
# an OFFLINE install needs in the store. Enabled by the installer ISO (round B).
{
  config,
  lib,
  pkgs,
  inputs,
  self,
  ...
}:
let
  cfg = config.survivalKit.installer;
  target = self.nixosConfigurations.survival-kit;
  # Every install targets a machine-specific /dev/disk/by-id/… name, so the few
  # device-dependent derivations (system, GRUB install script, disko script) are
  # always rebuilt on the target. Prebuild one variant per profile × encryption
  # setting and carry those derivations' build inputs (inputDerivation) → offline,
  # any disk name needs only a handful of tiny builds and no downloads.
  variants = lib.cartesianProduct {
    encrypt = [
      false
      true
    ];
    profile = [
      "lite"
      "full"
    ];
  };
  variantConfig =
    { encrypt, profile }:
    (target.extendModules {
      modules = [
        {
          survivalKit.disk = {
            device = "/dev/sda"; # representative; the real one is the by-id name
            inherit encrypt;
          };
          survivalKit.profile = profile;
        }
      ];
    }).config;
in
{
  options.survivalKit.installer.enable = lib.mkEnableOption "the survival-kit-install command and its offline dependencies";

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [
      (pkgs.callPackage ../../pkgs/survival-kit-install.nix {
        flakeSrc = self;
        inherit (inputs.disko.packages.${pkgs.stdenv.hostPlatform.system}) disko;
      })
    ];
    system.extraDependencies = lib.concatMap (
      v:
      let
        c = variantConfig v;
      in
      [
        c.system.build.toplevel
        c.system.build.destroyFormatMount # what `disko --mode destroy,format,mount` builds
        # build inputs of the device-dependent derivations
        c.system.build.toplevel.inputDerivation
        c.system.build.installBootLoader.inputDerivation
        c.system.build.destroyFormatMount.inputDerivation
      ]
    ) variants;
  };
}
