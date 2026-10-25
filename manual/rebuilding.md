# Rebuilding

The system configuration lives in `/etc/nixos` — a git repository the installer
created, so every change you make can be tracked (`git -C /etc/nixos log`). After
editing it, apply the change:

    sudo nixos-rebuild switch --flake /etc/nixos#survival-kit

The rebuild sees your edits to existing files right away; **new files** must be
added to git first (`sudo git -C /etc/nixos add <file>`). Committing what you
changed is a good habit:

    sudo git -C /etc/nixos commit -am "what I changed"

Every rebuild is a new *generation*. If a change breaks something, pick the
previous generation in the boot menu, or run:

    sudo nixos-rebuild switch --rollback

**Offline vs. online:** rolling back, and rebuilding an unchanged configuration,
work offline. Rebuilding a **changed** configuration usually needs internet —
the box carries the finished system, not the tools to build new parts of it.

## Files the installer wrote

- `hosts/survival-kit/selection.nix` — your install choices (disk, encryption).
- `hosts/survival-kit/hardware-detected.nix` — what the installer detected about
  this machine. **Reference only**: survival-kit ships drivers for most hardware
  instead. To use the detected settings, add `./hardware-detected.nix` to the
  `imports` in `hosts/survival-kit/default.nix`, then rebuild (online).
