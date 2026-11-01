# Inventory

The **Inventory** tile (<https://inventory.deck>) keeps track of what the household has:
**what** it is, **where** it is (rooms, shelves, boxes inside boxes) and **how many**.
Items can also have labels, notes and photos, and everything can be searched. It works
without internet. (It is Homebox.)

**First use.** Open Inventory and choose **Register**. As the email address, use your name
followed by `@inventory.deck`, e.g. **`anna@inventory.deck`**. It only has to *look* like an
email; nothing is ever sent to it (see [What's on this box](whats-on-this-box.html)). Pick a
password.

## Suggested setup: one shared household inventory

Homebox keeps things in **collections**. Everyone in a collection sees and edits the same
items. One person can belong to several collections and switch between them with the
collection dropdown in the sidebar, under the picture.

**The first person** to sign up gets a collection of their own. Make it the household's:

1. In the sidebar, open **Collection → Settings** and rename it to e.g. **Household**.
2. In **Collection → Invites**, choose **Create Invite**. Pick how long it stays valid and how many
   people may use it, then **Copy Invite Link**. The link is shown only once, so copy it
   now.
3. Give the link to the others.

**Everyone else** joins with the invite:

- **New here:** open the invite link and register through it. You land straight in
  Household.
- **Already have an account:** open the collection dropdown in the sidebar, choose **Join Existing
  Collection**, and paste the invite as the **Collection Invite Code**. Household is added
  next to what you already have.

**Something just for you?** From the same dropdown, **Create New Collection**. Nobody else
sees it unless you invite them.

## Good to know

- **Photos use disk space.** They're stored on this box, and the nightly backup (below)
  keeps a second copy on the same disk, so each photo takes about twice its size. Many
  large photos add up: check the disk now and then in [Content](content.html). One upload
  can be up to 32 MB.
- **Backups.** Every day at 23:00 (or at the next start, if the box was off) the inventory,
  with its photos, is saved to `/var/backup/homebox`. The last 7 days are kept in `daily/`,
  one folder per day, so a mistake noticed a few days later can still be undone. Unchanged
  photos are shared between the days, so 7 days take about the space of one. These copies
  are on the same disk; to survive a broken disk, copy the folder to a USB stick now and
  then:

      sudo cp -r /var/backup/homebox/daily/<newest day> /run/media/deck/<your stick>/

  To bring a copy back, see *Restoring a backup* in the developer guide's Inventory page.
- **What it doesn't do.** It doesn't warn about expiry dates, and it has no shopping lists.
  Items have built-in **Purchase Date** and **Warranty Expires** fields. For any other date
  (best-before, battery change), switch on **Advanced** in the item editor and add a
  **custom field**, e.g. *Best before* = `2027-03`. Custom fields are plain text, so nothing
  reminds you of the date. Looking up a product by its barcode needs the internet, so it doesn't work
  here.

Using the inventory from phones and other computers comes with the planned Wi-Fi hub mode.
