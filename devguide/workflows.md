# Workflows

## Change the installed box

    cd /etc/nixos
    sudo vim modules/…            # or any editor
    sudo nixos-rebuild switch --flake /etc/nixos#survival-kit
    sudo git -C /etc/nixos commit -am "what I changed"

New files must be `git add`-ed before the rebuild sees them. Each rebuild is a new
**generation**; if something breaks, choose an older one in the boot menu or run
`sudo nixos-rebuild switch --rollback`. Try first without switching:
`sudo nixos-rebuild build --flake /etc/nixos#survival-kit`.

## What works offline — and what doesn't

| Works offline | Needs internet (today) |
|---|---|
| Rolling back to an older generation | Rebuilding a **changed** configuration (new things must be built; build tools aren't on the box) |
| Rebuilding the **unchanged** configuration | Adding packages that aren't already in the store |
| Evaluating the config (`nix eval`, `nixos-option`) | Updating nixpkgs (`nix flake update`) |
| Adding wiki content (`.zim` drop-ins) | Building an ISO |

An "offline build kit" (build tools on the box) is planned.

## Develop on another machine

Clone or copy the repo to any Linux machine with Nix (flakes enabled):

    nix build .#nixosConfigurations.survival-kit.config.system.build.vm
    ./result/bin/run-survival-kit-vm      # quick VM, no install
    nix flake check                       # all tests
    nix build .#iso                       # installer ISO → result/iso/

## Pass changes on without internet

- **The configuration:** the repo is plain git — copy it on a USB stick (`git bundle create
  sk.bundle --all`, then `git pull` from the bundle on the other side).
- **Built systems:** `nix copy --to file:///media/stick/cache <store path>` exports what
  you built; the other box imports it with
  `nix copy --from file:///media/stick/cache <store path>` (add `--no-check-sigs` for your
  own unsigned builds) before `nixos-rebuild`, so it doesn't have to build.
- **A whole new system:** build an ISO and install from it.
