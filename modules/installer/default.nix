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
  # prebuild common disk names × encryption → a typical install builds nothing
  variants = lib.cartesianProduct {
    device = [
      "/dev/sda"
      "/dev/vda"
      "/dev/nvme0n1"
      "/dev/mmcblk0"
    ];
    encrypt = [
      false
      true
    ];
  };
  variantConfig = disk: (target.extendModules { modules = [ { survivalKit.disk = disk; } ]; }).config;
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
    system.extraDependencies =
      lib.concatMap (
        disk:
        let
          c = variantConfig disk;
        in
        [
          c.system.build.toplevel
          c.system.build.diskoScript
        ]
      ) variants
      ++ [
        # fallback for other disk names: rebuild the few device-dependent files
        pkgs.stdenv
        pkgs.stdenvNoCC
      ];
  };
}
