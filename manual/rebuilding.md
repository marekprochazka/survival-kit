# Rebuilding

The system configuration lives in `/etc/nixos`. After editing it, apply the
change with:

    sudo nixos-rebuild switch --flake /etc/nixos#survival-kit

Every rebuild is a new *generation*. If a change breaks something, pick the
previous generation in the boot menu, or run:

    sudo nixos-rebuild switch --rollback

Rebuilds work offline as long as nothing new needs downloading.
