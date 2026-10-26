# Passwords

The **Passwords** tile (<https://vault.deck>) is a password manager that lives on this
box — it works without internet. (It is Vaultwarden, compatible with Bitwarden apps.)

**First use.** Open Passwords and choose **Create account**. As the email address, use
your name followed by `@vault.deck`, e.g. **`anna@vault.deck`** — it only has to *look*
like an email; nothing is ever sent to it (see [What's on this box](whats-on-this-box.html)
for this convention). Then pick a **master password**.

**The master password cannot be recovered.** Your passwords are encrypted with it; nobody
can open them without it — not even someone with full access to this box. Write it down
and keep it somewhere safe.

**Everyone at this box can create their own account.** Each account is separate and
locked by its own master password.

**Backups.** Every day at 23:00 (or at the next start, if the box was off) a copy of the
password database is saved to `/var/backup/vaultwarden`. That copy is on the same disk —
to survive a broken disk, copy the folder to a USB stick now and then:

    sudo cp -r /var/backup/vaultwarden /run/media/deck/<your stick>/

Keep that stick safe: the passwords on it stay encrypted, but it is your vault.

Using Passwords from phones and other computers comes with the planned Wi-Fi hub mode.
