# Testing

All tests are flake checks: `checks/<name>.nix`, collected in `checks/default.nix`.

    nix flake check                                   # everything
    nix build .#checks.x86_64-linux.<name> -L         # one test, with logs
    nix build .#checks.x86_64-linux.eval              # all fast config checks

## Layers

| Layer | Checks | Speed | Runs |
|---|---|---|---|
| Static | `lint` (nixfmt, statix, deadnix) | seconds | pre-commit hook, CI, locally |
| Config | `eval-*` (disk, web, desktop, install, firstboot, iso) + `firstboot-script`, grouped as `eval` | seconds | CI, locally |
| VM | `boot`, `services`, `desktop`, `firstboot` | 1–5 min each | locally (needs KVM) |
| Install | installing from the ISO | long | by hand (QEMU / VirtualBox, offline) |

- **Config checks** evaluate the system and `assert` facts about it (e.g. "with encryption,
  root is on `/dev/mapper/cryptroot`"); `lib.assertMsg` gives readable failures. Variants
  are tested with `extendModules`, without editing files.
- **VM tests** use `pkgs.testers.runNixOSTest`: they boot the real host config
  (`checks/host-node.nix`, 2 GB RAM, first boot off) in QEMU and drive it from Python —
  `wait_for_unit`, `succeed("curl …")`, `send_chars` (typing), `wait_until_tty_matches`,
  `screenshot`. VM tests replace the disk layout, so disk/boot are covered by config checks
  and the install test.
- `firstboot-script` runs the real prompt script with scripted keyboard input and stand-ins
  for `usermod`/`chpasswd`.

## Writing a test

New config check: copy an `eval-*.nix`, add it to `evalChecks` in `checks/default.nix`.
New VM test: copy `services.nix` or `desktop.nix`, add it at the top level of
`checks/default.nix`. Write the test first and watch it fail, then make it pass.

## Pre-commit hook

`.githooks/pre-commit` runs the `lint` check. Enable once per clone:
`git config core.hooksPath .githooks`. Fix formatting with `nix fmt`.
