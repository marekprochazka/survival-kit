# Welcome to survival-kit

survival-kit is a self-contained computer: everything on it works **without
internet**. Open the dashboard at <https://deck> to see what's available.

On the very first start, survival-kit asks for your name and a password. The
password is what `sudo` and the text console (Ctrl+Alt+F2) ask for — the
desktop itself logs in automatically.

- [What's on this box](whats-on-this-box.html) — the services and how to reach them
- [Maps](maps.html) — offline maps, measuring distances, getting more maps
- [Language](language.html) — translate English ↔ Czech, dictionary, thesaurus
- [Content](content.html) — bring in wiki books, maps, languages, media and AI models from a stick
- [Content sticks](usb-sticks.html) — what's on the wiki and AI-model sticks; which model to pick
- [Passwords](passwords.html) — the offline password manager
- [Files](files.html) — your own files, and the box's books and maps to download
- [Inventory](inventory.html) — what the household has, where it is and how many
- [Media](media.html) — films, series and music; adding people
- [Chat](chat.html) — ask the local AI; it looks in the wiki first (full profile)
- [AI models](ai-models.html) — the models behind the chat (full profile)
- [Adding content](adding-content.html) — more wikis and documents
- [Rebuilding](rebuilding.html) — changing the system safely
- [Troubleshooting](troubleshooting.html) — when something doesn't work

The whole system is defined in one place: `/etc/nixos` (a Nix flake). Change it,
rebuild, and the machine follows. How all of it works — and how to change it — is
in the [developer guide](https://wiki.deck/content/survival-kit-dev).
