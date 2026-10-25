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
      nixosConfigurations.survival-kit = nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs self; };
        modules = [
          ./hosts/survival-kit
          disko.nixosModules.disko
        ];
      };

      # `nix fmt` → format the whole repo with the pinned nixfmt
      formatter.${system} = pkgs.nixfmt-tree;

      # tests (ADR-0003); `nix flake check` runs all, CI picks lint + eval-disk
      checks.${system} = import ./checks { inherit pkgs self inputs; };
    };
}
