{ config, lib, ... }:
let
  cfg = config.survivalKit.disk;

  # root filesystem reused in both the plain and encrypted branches
  rootFs = {
    type = "filesystem";
    format = "ext4";
    mountpoint = "/";
    mountOptions = [ "noatime" ]; # less disk wear on low-spec
  };
in
{
  options.survivalKit.disk = {
    device = lib.mkOption {
      type = lib.types.str;
      default = "/dev/vda";
      description = "Target disk device to install onto.";
    };
    encrypt = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Encrypt the root partition with LUKS.";
    };
  };

  config.disko.devices.disk.main = {
    type = "disk";
    inherit (cfg) device;
    content = {
      type = "gpt";
      partitions = {
        ESP = {
          size = "512M";
          type = "EF00";
          content = {
            type = "filesystem";
            format = "vfat";
            mountpoint = "/boot";
            mountOptions = [ "umask=0077" ];
          };
        };
        root = {
          size = "100%";
          content =
            if cfg.encrypt then
              {
                type = "luks";
                name = "cryptroot";
                settings.allowDiscards = true;
                content = rootFs;
              }
            else
              rootFs;
        };
      };
    };
  };
}
