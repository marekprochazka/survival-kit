{
  description = "survival-kit system";
  inputs = {
    # NixOS release channel; bump this to upgrade packages.
    # Independent of system.stateVersion: do NOT change that one when bumping.
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    disko = {
      url = "github:nix-community/disko";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };
  outputs =
    {
      self,
      nixpkgs,
      disko,
      ...
    }@inputs:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      nixosConfigurations = {
        # the installed system
        survival-kit = nixpkgs.lib.nixosSystem {
          inherit system;
          specialArgs = { inherit inputs self; };
          modules = [
            ./hosts/survival-kit
            disko.nixosModules.disko
          ];
        };
        # the live installer ISO (see packages.iso)
        installer = nixpkgs.lib.nixosSystem {
          inherit system;
          specialArgs = { inherit inputs self; };
          modules = [
            "${nixpkgs}/nixos/modules/installer/cd-dvd/installation-cd-minimal.nix"
            ./hosts/installer
          ];
        };
      };

      # `nix fmt` → format the whole repo with the pinned nixfmt
      formatter.${system} = pkgs.nixfmt-tree;

      # standalone builds, e.g. `nix build .#survival-kit-manual`
      packages.${system} = {
        survival-kit-manual = (pkgs.callPackage ./pkgs/books.nix { }).manual;
        survival-kit-devguide = (pkgs.callPackage ./pkgs/books.nix { }).devguide;
        survival-kit-install = pkgs.callPackage ./pkgs/survival-kit-install.nix {
          flakeSrc = self;
          inherit (disko.packages.${system}) disko;
        };
        # the installer ISO (big: ~3 GB) — build with utils/build-iso
        iso = self.nixosConfigurations.installer.config.system.build.isoImage;
      };

      # tests (ADR-0003); `nix flake check` runs all, CI builds lint + eval
      checks.${system} = import ./checks { inherit pkgs self inputs; };
    };
}
