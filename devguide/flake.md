# Flake

`flake.nix` is the single entry point. It has two parts.

## Inputs

- **`nixpkgs`** — `github:NixOS/nixpkgs/nixos-26.05`: the NixOS release (all packages and
  NixOS modules). Bumping this upgrades the system. **Do not** change
  `system.stateVersion` when you do — it records the release the box was *first installed*
  with, so stateful services keep reading their old data correctly.
- **`disko`** — declarative disk partitioning; `inputs.nixpkgs.follows = "nixpkgs"` makes it
  use our nixpkgs instead of its own copy.

`flake.lock` pins both to exact revisions and hashes. The sources of both are kept on
installed boxes, so the flake can be evaluated without internet (see [Base](base.html)).

## Outputs

| Output | What |
|---|---|
| `nixosConfigurations.survival-kit` | The installed system: `hosts/survival-kit` + disko's module |
| `nixosConfigurations.installer` | The live ISO: nixpkgs' `installation-cd-minimal.nix` + `hosts/installer` |
| `packages.iso` | The installer ISO image (`…installer.config.system.build.isoImage`) |
| `packages.survival-kit-install` | The installer command alone |
| `packages.survival-kit-manual`, `survival-kit-devguide` | The two wiki books (ZIM files) |
| `checks` | All tests — see [Testing](testing.html) |
| `formatter` | `nix fmt` → nixfmt over the whole repo |

Both systems get `specialArgs = { inherit inputs self; }`. That makes `inputs` (the flake
inputs) and `self` (this flake, incl. its source) available as arguments in every module.
The installer module needs both: `self` to bundle this exact source onto the ISO and to
prebuild the target system; `inputs` for the disko command.

## Useful commands

    nix flake show                       # list all outputs
    nix build .#iso                      # build the ISO → result/iso/
    nix build .#survival-kit-devguide    # build one book → result (a .zim)
    nix eval .#nixosConfigurations.survival-kit.config.networking.hostName
    nix flake check                      # run all tests

`nix eval …config.<option>` is the quickest way to see what any option ends up as.

Note: a flake inside a **git** repository only sees files git knows about. New files must be
`git add`-ed before Nix can see them (no commit needed).
