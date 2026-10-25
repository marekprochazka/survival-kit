# Rebuilding

The system configuration lives in `/etc/nixos` — a git repository the installer
created, so every change you make can be tracked (`git -C /etc/nixos log`). After
editing it, commit the change and apply it:

    cd /etc/nixos
    sudo git add -A && sudo git commit -m "what I changed"
    sudo nixos-rebuild switch --flake /etc/nixos#survival-kit

(Only committed files are seen by the rebuild.)

Every rebuild is a new *generation*. If a change breaks something, pick the
previous generation in the boot menu, or run:

    sudo nixos-rebuild switch --rollback

Rebuilds work offline as long as nothing new needs downloading.

## Files the installer wrote

- `hosts/survival-kit/selection.nix` — your install choices (disk, encryption).
- `hosts/survival-kit/hardware-detected.nix` — what the installer detected about
  this machine. **Reference only**: survival-kit ships drivers for most hardware
  instead. To use the detected settings, add `./hardware-detected.nix` to the
  `imports` in `hosts/survival-kit/default.nix`, commit, and rebuild.
