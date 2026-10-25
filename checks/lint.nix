# Layer 1 — static: formatting + lints over the flake's source tree.
{ pkgs, self, ... }:
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
  ''
