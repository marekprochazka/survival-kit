# Layer 3 — Files VM test (local only, ADR-0006 amendment): sign-up gives a private space with
# a folder per location and a read-only Library/; File Browser can't see the content tree; an
# exFAT drive becomes a folder people write to, goes away when pulled out and comes back when
# plugged in; the password reset command; a reboot keeps it all.
{
  pkgs,
  self,
  inputs,
  ...
}:
let
  mkTestZim = import ./test-zims.nix { inherit pkgs; };
  nearZim = mkTestZim "near-test"; # on this device
  curl = "curl --cacert /var/lib/survival-kit/tls/ca.crt";
in
pkgs.testers.runNixOSTest {
  name = "files";
  node.specialArgs = { inherit inputs self; };
  nodes.machine = {
    imports = [ (import ./host-node.nix { inherit inputs; }) ];
    virtualisation = {
      diskSize = 4096;
      emptyDiskImages = [ 1024 ]; # /dev/vdb: exFAT ("Big")
    };
    environment.systemPackages = [ pkgs.exfatprogs ];
  };
  testScript = ''
    import json
    import shlex
    from urllib.parse import quote

    FB = "https://files.deck/api"
    VIEW = "/var/lib/survival-kit-files/view/users"
    DATA = "/var/lib/survival-kit/data"
    DRIVES = "/var/lib/survival-kit/drives"
    ANNA, BEN = "anna@files.deck", "ben@files.deck"

    def code(method, path, token=None, data=None):
        auth = f"-H 'X-Auth: {token}'" if token else ""
        body = f"--data-binary {shlex.quote(data)}" if data is not None else ""
        return machine.succeed(
            f"${curl} -s -o /dev/null -w '%{{http_code}}' -X {method} {auth} {body} '{FB}{quote(path)}'").strip()

    def account(name, pw):
        return json.dumps({"username": name, "password": pw})

    def login(name, pw):
        return machine.succeed(f"${curl} -sf -X POST --data-binary {shlex.quote(account(name, pw))} {FB}/login").strip()

    def listing(token, path=""):
        out = machine.succeed(f"${curl} -sf -H 'X-Auth: {token}' '{FB}/resources/{quote(path)}'")
        return sorted(i["name"] for i in json.loads(out)["items"])

    def has(token, path, name, yes=True):
        test = f"${curl} -sf -H 'X-Auth: {token}' '{FB}/resources/{quote(path)}' | grep -q '\"name\":\"{name}\"'"
        machine.wait_until_succeeds(test if yes else f"! {test}", timeout=60)

    def download(token, path):
        return machine.succeed(f"${curl} -sf -H 'X-Auth: {token}' '{FB}/raw/{quote(path)}'")

    def ready():
        machine.wait_for_unit("filebrowser.service")
        machine.wait_for_unit("survival-kit-content.service")
        machine.wait_until_succeeds("${curl} -sf https://files.deck/health")
        machine.wait_until_succeeds("${curl} -sf https://content.deck/health")

    machine.wait_for_unit("multi-user.target")
    ready()
    machine.succeed(f"cp ${nearZim} {DATA}/wiki/near-test.zim")

    with subtest("sign-up gives a space"):
        assert code("POST", "/signup", data=account(ANNA, "anna-password-1")) == "200"
        assert code("POST", "/signup", data=account(BEN, "ben-password-12")) == "200"
        assert code("POST", "/signup", data=account("short@files.deck", "k7")) == "200"  # any length
        assert code("POST", "/signup", data=account("empty@files.deck", "")) == "400"
        # names File Browser would change into another account's folder, or hide (patched)
        for bad in ["anna..@files.deck", "anna b@files.deck", ".anna@files.deck"]:
            assert code("POST", "/signup", data=account(bad, "some-password-1")) == "400", bad
        assert code("POST", "/signup", data=account(ANNA, "some-password-1")) == "409"
        anna, ben = login(ANNA, "anna-password-1"), login(BEN, "ben-password-12")
        has(anna, "", "This device")
        has(anna, "", "Library")
        assert listing(anna) == ["Library", "This device"], listing(anna)
        machine.succeed("${curl} -sf -o /dev/null https://deck/health/files")

    with subtest("a new account's space appears inside File Browser, with the Library"):
        # these listings come from File Browser itself: the binds reached its sandbox
        assert "near-test.zim" in listing(anna, "Library/This device/wiki"), listing(anna, "Library/This device/wiki")
        assert "survival-kit.zim" in listing(anna, "Library/Built-in/wiki"), listing(anna, "Library/Built-in/wiki")
        book = quote("Library/This device/wiki/near-test.zim")
        machine.succeed(f"${curl} -sf -o /tmp/book.zim -H 'X-Auth: {anna}' '{FB}/raw/{book}'")
        machine.succeed(f"cmp {DATA}/wiki/near-test.zim /tmp/book.zim")  # downloads work

    with subtest("own files, private"):
        assert code("POST", "/resources/This device/notes.txt", anna, "my notes") == "200"
        assert machine.succeed(f"cat '{DATA}/files/{ANNA}/notes.txt'") == "my notes"
        assert listing(ben, "This device") == [], listing(ben, "This device")
        assert code("GET", f"/raw/users/{ANNA}/This device/notes.txt", ben) != "200"

    with subtest("Library is read-only, and so is the top of a space"):
        # read-only bind; nginx answers 403 before File Browser would fail with a 500
        assert code("POST", "/resources/Library/This device/wiki/x.zim", anna, "x") == "403"
        assert code("DELETE", "/resources/Library/This device/wiki/near-test.zim", anna) == "403"
        # a copy into Library names it only in the destination parameter
        assert code("POST", "/resources/This device/c.txt", anna, "x") == "200"
        copy = "/resources/This device/c.txt?action=copy&destination=%2FLibrary%2Fc.txt&override=false"
        assert machine.succeed(
            f"${curl} -s -o /dev/null -w '%{{http_code}}' -X PATCH -H 'X-Auth: {anna}' '{FB}{copy.replace(' ', '%20')}'"
        ).strip() == "403"
        assert code("GET", "/resources/Library/This device/wiki", anna) == "200"  # reading still works
        machine.succeed(f"test -f {DATA}/wiki/near-test.zim")
        machine.fail(f"test -e {DATA}/wiki/x.zim")
        assert code("POST", "/resources/Library/new.txt", anna, "x") == "403"  # Library/ itself is root's
        machine.fail(f"touch '{VIEW}/{ANNA}/Library/This device/wiki/y'")  # read-only even for root
        assert code("POST", "/resources/top.txt", anna, "x") == "403"
        machine.fail(f"test -e '{VIEW}/{ANNA}/top.txt'")

    with subtest("File Browser can't see the content tree"):
        pid = machine.succeed("systemctl show -p MainPID --value filebrowser.service").strip()
        machine.fail(f"nsenter -t {pid} -m -- test -e {DATA}/wiki")
        machine.succeed(f"nsenter -t {pid} -m -- test -e '{VIEW}/{ANNA}/This device/notes.txt'")

    with subtest("a drive becomes a folder"):
        machine.succeed("mkfs.exfat -L BIG /dev/vdb")
        uuid = machine.succeed("blkid -s UUID -o value /dev/vdb").strip()
        machine.succeed("udevadm settle")
        r = json.loads(machine.succeed(f"${curl} -s -X POST 'https://content.deck/api/drives/add?uuid={uuid}&name=Big'"))
        assert r["mounted"], r
        has(anna, "", "Big")
        has(anna, "Library", "Big")
        assert code("POST", "/resources/Big/photo.txt", anna, "a photo") == "200"
        assert machine.succeed(f"cat {DRIVES}/{uuid}/survival-kit/files/{ANNA}/photo.txt") == "a photo"

    with subtest("unplug and plug back"):
        pci = machine.succeed("readlink -f /sys/block/vdb/device/..").strip()
        machine.succeed(f"echo 1 > {pci}/remove")
        has(anna, "", "Big", yes=False)
        has(anna, "Library", "Big", yes=False)
        assert download(anna, "This device/notes.txt") == "my notes"
        machine.succeed("echo 1 > /sys/bus/pci/rescan")
        has(anna, "", "Big")
        machine.wait_until_succeeds(f"${curl} -sf -H 'X-Auth: {anna}' '{FB}/raw/Big/photo.txt' | grep -q 'a photo'", timeout=60)

    with subtest("password reset"):
        machine.succeed(f"printf 'new-password-123\\nnew-password-123\\n' | survival-kit-files reset-password {BEN}")
        machine.fail(f"printf 'one\\ntwo\\n' | survival-kit-files reset-password {BEN}")  # differ
        machine.fail(f"printf '\\n\\n' | survival-kit-files reset-password {BEN}")  # empty
        ready()
        login(BEN, "new-password-123")
        assert code("POST", "/login", data=account(BEN, "ben-password-12")) != "200"

    with subtest("a reboot keeps it"):
        machine.shutdown()
        machine.start()
        ready()
        anna = login(ANNA, "anna-password-1")
        machine.wait_until_succeeds(f"${curl} -sf -H 'X-Auth: {anna}' '{FB}/raw/This%20device/notes.txt' | grep -q 'my notes'", timeout=60)
        machine.wait_until_succeeds(f"${curl} -sf -H 'X-Auth: {anna}' '{FB}/raw/Big/photo.txt' | grep -q 'a photo'", timeout=60)
        assert "survival-kit.zim" in listing(anna, "Library/Built-in/wiki")
  '';
}
