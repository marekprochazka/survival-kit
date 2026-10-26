# Testing

All tests are flake checks: `checks/<name>.nix`, collected in `checks/default.nix`.

    nix flake check                                   # everything
    nix build .#checks.x86_64-linux.<name> -L         # one test, with logs
    nix build .#checks.x86_64-linux.eval              # all fast config checks

## Layers

| Layer | Checks | Speed | Runs |
|---|---|---|---|
| Static | `lint` (nixfmt, statix, deadnix) | seconds | pre-commit hook, CI, locally |
| Config | `eval-*` (disk, web, desktop, install, firstboot, iso, tls, vaultwarden, ollama, profiles, content, chat) + `firstboot-script` + `tls-script` + `content-unit` + `lookup-unit` + `chat-unit` + `panel-drift`, grouped as `eval` | seconds | CI, locally |
| VM | `boot`, `services`, `desktop`, `firstboot` | 1–5 min each | locally (needs KVM) |
| Closure | `lite-closure` (no Ollama anywhere in a lite system) | minutes (builds lite) | locally |
| Install | installing from the ISO | long | by hand (QEMU / VirtualBox, offline) |

- **Config checks** evaluate the system and `assert` facts about it (e.g. "with encryption,
  root is on `/dev/mapper/cryptroot`"); `lib.assertMsg` gives readable failures. Variants
  are tested with `extendModules`, without editing files.
- **VM tests** use `pkgs.testers.runNixOSTest`: they boot the real host config
  (`checks/host-node.nix`, 2 GB RAM, first boot off) in QEMU and drive it from Python —
  `wait_for_unit`, `succeed("curl …")`, `send_chars` (typing), `wait_until_tty_matches`,
  `screenshot`. VM tests replace the disk layout, so disk/boot are covered by config checks
  and the install test.
- `panel-drift` compares our XFCE panel default with XFCE's stock one (minus our plugin);
  it fails when a nixpkgs update changes the stock layout — re-copy it then.
- `firstboot-script` runs the real prompt script with scripted keyboard input (incl. a real
  SIGINT and end-of-input) and stand-ins
  for `usermod`/`chpasswd`.
- `content-unit` runs the content manager's Python tests (`unittest`, stdlib) — names,
  space, uploads, the HTTP API on a real local server — with stand-ins for Kiwix/Ollama.
- `lookup-unit` / `chat-unit`: the wiki lookup (fixtures = real Kiwix output) and the chat
  (storage, queue, pipeline, events on a real local server) with stand-ins. The `services` VM
  test runs both against the real Kiwix with **`checks/fake-ollama.py`** in place of a model.
- `tls-script` runs the real certificate script in the build sandbox: creates the CA once,
  keeps it, re-issues the site certificate on new names or a mismatched key.
- VM tests talk HTTPS like Firefox does: `curl --cacert /var/lib/survival-kit/tls/ca.crt`.
- **systemd start limit:** a unit started more than 5 times within 10 s is refused
  (`start-limit-hit`). Tests that restart a unit often can hit it — fix the unit when real
  use could too (as for `kiwix-library`), not the test.

## Writing a test

New config check: copy an `eval-*.nix`, add it to `evalChecks` in `checks/default.nix`.
New VM test: copy `services.nix` or `desktop.nix`, add it at the top level of
`checks/default.nix`. Write the test first and watch it fail, then make it pass.

## Pre-commit hook

`.githooks/pre-commit` runs the `lint` check. Enable once per clone:
`git config core.hooksPath .githooks`. Fix formatting with `nix fmt`.
