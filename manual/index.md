# Welcome to survival-kit

survival-kit is a self-contained computer: everything on it works **without
internet**. Open the dashboard at <https://deck> to see what's available.

On the very first start, survival-kit asks for your name and a password. The
password is what `sudo` and the text console (Ctrl+Alt+F2) ask for — the
desktop itself logs in automatically.

- [What's on this box](whats-on-this-box.html) — the services and how to reach them
- [Passwords](passwords.html) — the offline password manager
- [AI models](ai-models.html) — local AI in the terminal (full profile)
- [Adding content](adding-content.html) — more wikis and documents
- [Rebuilding](rebuilding.html) — changing the system safely
- [Troubleshooting](troubleshooting.html) — when something doesn't work

The whole system is defined in one place: `/etc/nixos` (a Nix flake). Change it,
rebuild, and the machine follows. How all of it works — and how to change it — is
in the [developer guide](https://wiki.deck/content/survival-kit-dev).
