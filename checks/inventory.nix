# Layer 3 — Inventory VM test (local only): Homebox behind nginx — dashboard tile and health,
# a page that loads nothing from other hosts, sign-up and login, items with a quantity and
# search, a 5 MB upload (nginx + Homebox limits), and nightly backups whose older dated
# copies stay untouched by later runs (hard links) and are kept at 7.
{
  pkgs,
  self,
  inputs,
  ...
}:
let
  curl = "curl --cacert /var/lib/survival-kit/tls/ca.crt";
in
pkgs.testers.runNixOSTest {
  name = "inventory";
  node.specialArgs = { inherit inputs self; };
  nodes.machine = {
    imports = [ (import ./host-node.nix { inherit inputs; }) ];
    virtualisation.diskSize = 4096;
    environment.systemPackages = [ pkgs.sqlite ];
  };
  testScript = ''
    import json
    import re
    import shlex

    API = "https://inventory.deck/api/v1"
    BK = "/var/backup/homebox"

    def call(method, path, token=None, data=None):
        auth = f"-H {shlex.quote('Authorization: ' + token)}" if token else ""
        body = f"-H 'Content-Type: application/json' --data-binary {shlex.quote(json.dumps(data))}" if data is not None else ""
        return json.loads(machine.succeed(f"${curl} -sf -X {method} {auth} {body} '{API}{path}'") or "null")

    def items_in(db):
        return machine.succeed(f"sqlite3 {db} 'select count(*) from items'").strip()

    machine.wait_for_unit("homebox.service")
    machine.wait_for_unit("nginx.service")

    with subtest("up, healthy and on the dashboard"):
        machine.wait_until_succeeds(f"${curl} -sf -o /dev/null {API}/status", timeout=60)
        machine.succeed("${curl} -sf -o /dev/null https://deck/health/inventory")
        page = machine.succeed("${curl} -sf https://deck/")
        assert 'href="https://inventory.deck/"' in page, "Inventory tile link"

    with subtest("the page loads nothing from other hosts"):
        html = machine.succeed("${curl} -sf https://inventory.deck/")
        refs = re.findall(r'(?:src|href)="([^"]+)"', html)
        external = [r for r in refs if re.match(r"(https?:)?//", r) and "//inventory.deck" not in r]
        assert not external, f"page references other hosts: {external}"
        assets = [r for r in refs if r.startswith("/") and not r.startswith("//") and re.search(r"\.(js|css)$", r)]
        assert assets, f"no scripts/styles found in the page: {refs}"
        for a in assets:
            body = machine.succeed(f"${curl} -sf 'https://inventory.deck{a}'")
            for host in ["fonts.googleapis", "fonts.gstatic", "cdn.jsdelivr", "unpkg.com", "cdnjs."]:
                assert host not in body, f"{a} loads from {host}"

    with subtest("sign-up and login through nginx"):
        call("POST", "/users/register", data={"name": "Anna", "email": "anna@inventory.deck", "password": "test-password-1"})
        token = call("POST", "/users/login", data={"username": "anna@inventory.deck", "password": "test-password-1"})["token"]
        assert token.startswith("Bearer "), token

    with subtest("items with a quantity, found by search"):
        garage = call("POST", "/locations", token, {"name": "Garage"})["id"]
        hammer = call("POST", "/items", token, {"name": "Hammer", "quantity": 3, "locationId": garage})["id"]
        found = call("GET", "/items?q=Hammer", token)["items"]
        assert [(i["name"], i["quantity"]) for i in found] == [("Hammer", 3)], found

    with subtest("a 5 MB upload passes nginx and Homebox"):
        machine.succeed("head -c 5000000 /dev/urandom > /tmp/big.bin")
        status = machine.succeed(
            f"${curl} -s -o /dev/null -w '%{{http_code}}' -H {shlex.quote('Authorization: ' + token)}"
            f" -F file=@/tmp/big.bin -F name=receipt.bin -F type=attachment {API}/items/{hammer}/attachments").strip()
        assert status.startswith("2"), f"upload answered {status}"

    with subtest("backup: consistent database, attachments, today's dated copy"):
        machine.succeed("systemctl start backup-homebox.service")
        today = machine.succeed("date +%F").strip()
        assert machine.succeed(f"sqlite3 {BK}/latest/homebox.db 'PRAGMA integrity_check'").strip() == "ok"
        # not WAL: opening a copy must not create -wal/-shm files beside it (they would change
        # the dated folder's age and could be restored next to the wrong database)
        assert machine.succeed(f"sqlite3 {BK}/latest/homebox.db 'PRAGMA journal_mode'").strip() == "delete"
        machine.fail(f"ls {BK}/latest/homebox.db-wal {BK}/latest/homebox.db-shm")
        machine.succeed(f"find {BK}/latest -type f -size 5000000c | grep -q .")  # the upload
        assert items_in(f"{BK}/daily/{today}/homebox.db") == "1"

    with subtest("a later backup leaves older copies untouched (hard links)"):
        machine.succeed(f"cp -al {BK}/daily/{today} {BK}/daily/2000-01-01")
        machine.succeed(f"touch -d 2000-01-01 {BK}/daily/2000-01-01")
        call("POST", "/items", token, {"name": "Saw", "quantity": 1, "locationId": garage})
        machine.succeed("systemctl start backup-homebox.service")
        assert items_in(f"{BK}/latest/homebox.db") == "2"
        assert items_in(f"{BK}/daily/2000-01-01/homebox.db") == "1", "yesterday's copy was changed"

    with subtest("the newest 7 dated copies are kept"):
        for d in range(2, 10):
            machine.succeed(f"cp -al {BK}/daily/{today} {BK}/daily/2001-01-0{d}")
            machine.succeed(f"touch -d 2001-01-0{d} {BK}/daily/2001-01-0{d}")
        # a half-made copy from an interrupted run (e.g. disk full) under its temporary name
        machine.succeed(f"mkdir -p {BK}/daily/.{today}.tmp/partial")
        machine.succeed("systemctl start backup-homebox.service")
        kept = machine.succeed(f"ls -A {BK}/daily").split()
        assert len(kept) == 7 and today in kept and "2000-01-01" not in kept, kept
        machine.succeed(f"test -s {BK}/daily/{today}/homebox.db")
  '';
}
