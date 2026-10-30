# Layer 3 — added drives VM test (local only, ADR-0006): three extra virtual disks — an
# empty ext4 drive, a pre-filled exFAT drive and a FAT32 stick — added through the content
# manager's API; books spread over this device and two drives; auto-resolve (drive and this
# device); reboot with a listed drive missing; a real unplug (PCI remove) + plug back; forget.
{
  pkgs,
  self,
  inputs,
  ...
}:
let
  mkTestZim = import ./test-zims.nix { inherit pkgs; };
  nearZim = mkTestZim "near-test"; # on this device (and a copy on the exFAT drive)
  farZim = mkTestZim "far-test"; # already on the exFAT drive when it is added
  bigZim = mkTestZim "big-test"; # imported to the ext4 drive
  austriaMap = (import ./test-maps.nix { inherit pkgs; }).austria;
  curl = "curl --cacert /var/lib/survival-kit/tls/ca.crt";
in
pkgs.testers.runNixOSTest {
  name = "drives";
  node.specialArgs = { inherit inputs self; };
  nodes.machine = {
    imports = [ (import ./host-node.nix { inherit inputs; }) ];
    virtualisation = {
      diskSize = 4096; # the content manager keeps ≥ 2 GiB free on this device
      emptyDiskImages = [
        3072 # /dev/vdb: ext4, empty ("the big drive"; 2 GiB are always kept free)
        1024 # /dev/vdc: exFAT, pre-filled with a survival-kit/ folder
        256 # /dev/vdd: FAT32 stick (refused)
      ];
    };
    environment.systemPackages = [
      pkgs.e2fsprogs
      pkgs.exfatprogs
      pkgs.dosfstools
    ];
  };
  testScript = ''
    import json
    import shlex

    EXT = "11111111-2222-3333-4444-555555555555"
    FAT = "ABCD-1234"
    EXFAT = None  # mkfs.exfat can't set the serial: read back after formatting
    DRIVES = "/var/lib/survival-kit/drives"
    REGISTRY = "/var/lib/survival-kit/content/drives.json"
    GONE = "0000-DEAD"  # listed, never plugged in
    CATALOG = "${curl} -sf 'https://wiki.deck/catalog/v2/entries?count=-1'"

    def api(method, path):
        return json.loads(machine.succeed(f"${curl} -s -X {method} 'https://content.deck{path}'"))

    def code(method, path):
        return machine.succeed(f"${curl} -s -o /dev/null -w '%{{http_code}}' -X {method} 'https://content.deck{path}'").strip()

    def status():
        return api("GET", "/api/status")

    def wiki(location):
        return {i["name"]: i["status"] for i in status()["wiki"] if i["location"] == location}

    def served(book):
        machine.wait_until_succeeds(f"${curl} -sfL https://wiki.deck/content/{book} | grep -q '{book} test page'", timeout=120)

    def gone(book):
        machine.wait_until_succeeds(f"! {CATALOG} | grep -q '{book}'", timeout=120)

    def map_code():
        return machine.succeed("${curl} -s -o /dev/null -w '%{http_code}' -r 0-126 https://maps.deck/imported/austria.pmtiles").strip()

    def added(uuid):
        return next(d for d in status()["drives"]["added"] if d["uuid"] == uuid)

    def ready():
        machine.wait_for_unit("survival-kit-content.service")
        machine.wait_for_unit("kiwix-serve.service")
        machine.wait_until_succeeds("${curl} -sf https://content.deck/health")

    machine.wait_for_unit("multi-user.target")
    ready()

    with subtest("drives are offered; FAT32 with its reason; the system disk never"):
        machine.succeed(f"mkfs.ext4 -q -L BIG -U {EXT} /dev/vdb")
        machine.succeed("mkfs.exfat -L PHOTOS /dev/vdc")
        EXFAT = machine.succeed("blkid -s UUID -o value /dev/vdc").strip()
        machine.succeed(f"mkfs.vfat -n STICK -i {FAT.replace('-', "")} /dev/vdd")
        # pre-fill the exFAT drive: a new book, an unreadable one, a copy of a device book
        machine.succeed("mkdir -p /mnt && mount /dev/vdc /mnt && mkdir -p /mnt/survival-kit/wiki /mnt/other")
        machine.succeed("cp ${farZim} /mnt/survival-kit/wiki/far-test.zim")
        machine.succeed("echo garbage > /mnt/survival-kit/wiki/junk.zim")
        machine.succeed("cp ${nearZim} /mnt/survival-kit/wiki/near-test.zim")
        machine.succeed("echo mine > /mnt/other/notes.txt && umount /mnt")
        machine.succeed("cp ${nearZim} /var/lib/survival-kit/data/wiki/near-test.zim")
        machine.succeed("systemctl restart survival-kit-library.service")
        served("near-test")
        machine.succeed("udevadm settle")
        offered = {d["uuid"]: d for d in status()["drives"]["available"]}
        assert set(offered) == {EXT, EXFAT, FAT}, offered
        assert "FAT32" in offered[FAT]["refusal"], offered[FAT]
        assert code("POST", f"/api/drives/add?uuid={FAT}") == "400"

    with subtest("an empty ext4 drive is added and takes imports"):
        r = api("POST", f"/api/drives/add?uuid={EXT}&name=Big")
        assert r["mounted"], r
        machine.succeed(f"findmnt -n -S UUID={EXT} -T {DRIVES}/{EXT}")
        machine.succeed(f"test -f {DRIVES}/{EXT}/survival-kit/survival-kit.json")
        r = json.loads(machine.succeed(
            f"${curl} -s 'https://content.deck/api/upload?kind=map&file=austria.pmtiles&to={EXT}' -T ${austriaMap}"))
        assert r.get("result") == "added", r
        # on the drive itself (seen from outside the content manager's sandbox)
        machine.succeed(f"test -s {DRIVES}/{EXT}/survival-kit/maps/austria.pmtiles")
        assert map_code() == "206", "the map is served from the drive, byte ranges included"
        r = json.loads(machine.succeed(
            f"${curl} -s 'https://content.deck/api/upload?kind=wiki&file=big-test.zim&to={EXT}' -T ${bigZim}"))
        assert r.get("result") == "added", r
        served("big-test")

    with subtest("a pre-filled exFAT drive is used in place, checked"):
        r = api("POST", f"/api/drives/add?uuid={EXFAT}&name=Photos")
        assert r["mounted"], r
        served("far-test")
        assert wiki(EXFAT) == {"far-test.zim": "in_use", "junk.zim": "invalid", "near-test.zim": "duplicate"}, wiki(EXFAT)
        # books from this device and both drives, all in the wiki at once
        for book in ["near-test", "big-test", "far-test"]:
            served(book)
        assert wiki("device") == {"near-test.zim": "in_use"}, wiki("device")

    with subtest("auto-resolve moves, never deletes"):
        r = api("POST", f"/api/resolve?at={EXFAT}")
        assert sorted(r["moved"]) == ["junk.zim", "near-test.zim"], r
        aside = machine.succeed(f"find {DRIVES}/{EXFAT}/survival-kit-set-aside -type f -printf '%f %s\\n' | sort")
        assert "junk.zim" in aside and "near-test.zim" in aside, aside
        assert wiki(EXFAT) == {"far-test.zim": "in_use"}, wiki(EXFAT)
        machine.succeed(f"test -f {DRIVES}/{EXFAT}/other/notes.txt")  # never touched
        served("near-test")  # the device's copy still serves

    with subtest("auto-resolve on this device (a rename inside the content manager's sandbox)"):
        machine.succeed("echo garbage > /var/lib/survival-kit/data/wiki/junk-here.zim")
        machine.succeed("systemctl restart survival-kit-library.service")
        assert wiki("device").get("junk-here.zim") == "invalid", wiki("device")
        r = api("POST", "/api/resolve?at=device")
        assert r.get("moved") == ["junk-here.zim"], r
        machine.succeed("test -f /var/lib/survival-kit/data/.set-aside/*/wiki/junk-here.zim")
        served("near-test")

    with subtest("added drives are hidden from the desktop"):
        machine.succeed("udevadm settle")
        machine.succeed("udevadm info --query=property /dev/vdb | grep -q '^UDISKS_IGNORE=1'")
        machine.succeed("udevadm info --query=property /dev/vdc | grep -q '^UDISKS_IGNORE=1'")
        machine.fail("udevadm info --query=property /dev/vdd | grep -q '^UDISKS_IGNORE=1'")

    with subtest("a reboot keeps the drives, also with a listed drive missing"):
        listed = json.loads(machine.succeed(f"cat {REGISTRY}"))
        listed.append({"uuid": GONE, "fstype": "ext4", "name": "Gone", "added": "2026-10-30"})
        machine.succeed(f"echo {shlex.quote(json.dumps(listed))} > {REGISTRY}")
        machine.shutdown()
        machine.start()
        ready()
        machine.succeed(f"findmnt -n -T {DRIVES}/{EXT} && findmnt -n -T {DRIVES}/{EXFAT}")
        for book in ["near-test", "big-test", "far-test"]:
            served(book)
        assert map_code() == "206"
        assert added(GONE)["mounted"] is False and added(GONE)["error"] == "not connected", added(GONE)
        assert 'data-drive="' + GONE + '" data-action="reconnect"' in machine.succeed("${curl} -sf https://content.deck/")
        machine.succeed(f"${curl} -sf -X POST https://content.deck/api/drives/{GONE}/forget")

    with subtest("a drive really pulled out: noticed on its own, the rest keeps working"):
        pci = machine.succeed("readlink -f /sys/block/vdb/device/..").strip()
        machine.succeed(f"echo 1 > {pci}/remove")  # the disk vanishes, like a pulled USB cable
        gone("big-test")
        machine.wait_until_succeeds("test $(${curl} -s -o /dev/null -w '%{http_code}' -r 0-126 https://maps.deck/imported/austria.pmtiles) = 404")
        machine.fail(f"findmnt -n -T {DRIVES}/{EXT} -S UUID={EXT}")  # the dead mount is cleared
        served("far-test")
        served("near-test")
        assert added(EXT)["mounted"] is False, added(EXT)
        assert 'data-drive="' + EXT + '" data-action="reconnect"' in machine.succeed("${curl} -sf https://content.deck/")
        # an import to this device still works (no crash on the dead drive)
        r = json.loads(machine.succeed(
            "${curl} -s 'https://content.deck/api/upload?kind=wiki&file=near-test.zim&to=device' -T ${nearZim}"))
        assert r.get("result") == "replaced", r

    with subtest("plugged back in: mounted again on its own"):
        machine.succeed("echo 1 > /sys/bus/pci/rescan")
        served("big-test")
        machine.wait_until_succeeds("test $(${curl} -s -o /dev/null -w '%{http_code}' -r 0-126 https://maps.deck/imported/austria.pmtiles) = 206")
        assert added(EXT)["mounted"] is True, added(EXT)
        r = api("POST", f"/api/drives/{EXT}/reconnect")  # the button still works when all is fine
        assert r["mounted"], r

    with subtest("forget: content gone from the box, files stay on the drive"):
        r = api("POST", f"/api/drives/{EXFAT}/forget")
        assert r["result"] == "forgotten", r
        gone("far-test")
        machine.fail(f"findmnt -n -T {DRIVES}/{EXFAT} -S UUID={EXFAT}")
        machine.succeed("mount /dev/vdc /mnt")
        machine.succeed("test -f /mnt/survival-kit/wiki/far-test.zim && test -d /mnt/survival-kit-set-aside")
        machine.succeed("umount /mnt")
        assert EXFAT not in [d["uuid"] for d in status()["drives"]["added"]]
  '';
}
