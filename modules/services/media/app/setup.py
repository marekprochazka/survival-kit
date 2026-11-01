"""survival-kit-media-setup — Jellyfin's one-time setup (spec 2026-11-01-media). Stdlib only.

The first-boot prompt pipes two lines into it: the owner's name and password (never on a
command line, never written to disk). It finishes Jellyfin's setup wizard with that account,
creates the three libraries (films, series, music) on the box's media index, applies the
starting offline settings and makes the box's own key for rescans. Once: after that the
settings are the owner's — nothing here runs again (with the key in place a second run
changes nothing, exit 2). A setup that stopped half-way (the wizard done, no key yet) is
finished by running it again with the same name and password: `sudo survival-kit-media-setup`
(it asks for them when run in a terminal).

Exit codes: 0 done, 1 failed (one line on stderr), 2 Jellyfin was already set up, 3 done but
the name had to change (the note is on stderr).
"""

import getpass
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CLIENT = 'MediaBrowser Client="survival-kit", Device="box", DeviceId="survival-kit-setup", Version="1"'
KEY_APP = "survival-kit"
# image sources that read the file itself; all the others are internet services
LOCAL_IMAGES = {"Embedded Image Extractor", "Screen Grabber", "Image Extractor"}
LIBRARIES = (("Movies", "movies", "movies"), ("Shows", "tvshows", "shows"), ("Music", "music", "music"))


class SetupError(Exception):
    """Setup failed; the message is one line for the console. status: Jellyfin's HTTP answer."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class AlreadyDone(Exception):
    """Jellyfin's setup wizard was already completed — nothing is changed."""


def _get(d, key):
    """Jellyfin answers in PascalCase or camelCase depending on the endpoint."""
    return d.get(key, d.get(key[0].lower() + key[1:]))


class Api:
    """Jellyfin's API. deadline (time.monotonic()): no call starts or waits past it."""

    def __init__(self, url, token=None, deadline=None):
        self.url = url.rstrip("/")
        self.token = token
        self.deadline = deadline

    def call(self, method, path, body=None, query=None, timeout=30):
        """One request, retried until the deadline (else for 2 min) while Jellyfin can't take
        it yet: 503 while it is still starting (though /System/Info/Public already works), no
        answer at all for a moment after its network settings change (it re-binds)."""
        give_up = self.deadline if self.deadline is not None else time.monotonic() + 120
        while True:
            try:
                return self._once(method, path, body, query, timeout)
            except SetupError as e:
                if e.status not in (None, 503) or time.monotonic() + 2 >= give_up:
                    raise
            time.sleep(2)

    def _once(self, method, path, body, query, timeout):
        if self.deadline is not None:
            left = self.deadline - time.monotonic()
            if left <= 0:
                raise SetupError("Jellyfin took too long to set up", "timeout")
            timeout = min(timeout, left)
        url = self.url + path + ("?" + urllib.parse.urlencode(query) if query else "")
        auth = CLIENT + (f', Token="{self.token}"' if self.token else "")
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Authorization": auth, "Content-Type": "application/json"})
        if method == "POST" and data is None:
            req.data = b""
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            e.close()
            raise SetupError(f"Jellyfin refused {method} {path} ({e.code})", e.code) from e
        except (OSError, ValueError) as e:
            raise SetupError(f"Jellyfin can't be reached ({e})") from e
        return json.loads(raw) if raw.strip() else None


def clean_user_name(name):
    """A Jellyfin user name: letters (any script), digits, spaces and - ' . _ @ +."""
    kept = re.sub(r"[^\w \-'.@+]", "", name, flags=re.UNICODE)
    kept = " ".join(kept.split())
    return kept or "owner"


def library_options(api, content_type):
    """Nothing from the internet, no heavy image extraction, no file watching (the box asks
    for rescans); pictures only from the files themselves."""
    offered = api.call("GET", "/Libraries/AvailableOptions",
                       query={"libraryContentType": content_type, "isNewLibrary": "true"})
    types = []
    for t in _get(offered, "TypeOptions") or []:
        local = [_get(f, "Name") for f in _get(t, "ImageFetchers") or [] if _get(f, "Name") in LOCAL_IMAGES]
        types.append({"Type": _get(t, "Type"), "MetadataFetchers": [], "MetadataFetcherOrder": [],
                      "ImageFetchers": local, "ImageFetcherOrder": local})
    return {
        "Enabled": True,
        "EnableRealtimeMonitor": False,
        "EnableInternetProviders": False,
        "SaveLocalMetadata": False,
        "MetadataSavers": [],
        "EnableChapterImageExtraction": False,
        "ExtractChapterImagesDuringLibraryScan": False,
        "EnableTrickplayImageExtraction": False,
        "ExtractTrickplayImagesDuringLibraryScan": False,
        "EnableLUFSScan": False,
        "AutomaticRefreshIntervalDays": 0,
        "SubtitleDownloadLanguages": [],
        "TypeOptions": types,
    }


def _write_key(key_file, key):
    """Root-only, written whole (a temp file renamed into place)."""
    path = Path(key_file)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".api-key-")  # mode 0600
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    os.replace(tmp, path)


def run(api, name, password, key_file, library, log=sys.stderr):
    """Set Jellyfin up once — or finish a setup that stopped after the wizard; returns the
    user name used. AlreadyDone / SetupError."""
    info = api.call("GET", "/System/Info/Public")
    resuming = bool(_get(info, "StartupWizardCompleted"))
    if resuming and Path(key_file).exists():
        raise AlreadyDone()
    user = clean_user_name(name)
    if user != name:
        print(f"Media: your name there is \"{user}\" (Jellyfin allows fewer characters).", file=log)
    if not resuming:
        api.call("POST", "/Startup/Configuration",
                 {"ServerName": "survival-kit", "UICulture": "en-US", "MetadataCountryCode": "US",
                  "PreferredMetadataLanguage": "en"})
        api.call("GET", "/Startup/User")  # Jellyfin makes its first user here when there is none
        api.call("POST", "/Startup/User", {"Name": user, "Password": password})
        api.call("POST", "/Startup/RemoteAccess", {"EnableRemoteAccess": False, "EnableAutomaticPortMapping": False})
        api.call("POST", "/Startup/Complete")
    try:
        auth = api.call("POST", "/Users/AuthenticateByName", {"Username": user, "Pw": password})
    except SetupError as e:
        if resuming and e.status == 401:
            raise SetupError("Media is set up with another name or password — use the ones it was set up with") from e
        raise
    owner = Api(api.url, _get(auth, "AccessToken"), api.deadline)
    uid = _get(_get(auth, "User"), "Id")
    have = {_get(f, "Name") for f in owner.call("GET", "/Library/VirtualFolders") or []}
    for title, content_type, folder in LIBRARIES:
        if title in have:
            continue
        owner.call("POST", "/Library/VirtualFolders",
                   {"LibraryOptions": library_options(owner, content_type)},
                   query={"name": title, "collectionType": content_type, "paths": f"{library}/{folder}",
                          "refreshLibrary": "false"})
    policy = _get(owner.call("GET", f"/Users/{uid}"), "Policy")
    policy.update(EnableVideoPlaybackTranscoding=False, EnableAudioPlaybackTranscoding=True,
                  EnablePlaybackRemuxing=True)
    owner.call("POST", f"/Users/{uid}/Policy", policy)
    config = owner.call("GET", "/System/Configuration")
    config["PluginRepositories"] = []
    owner.call("POST", "/System/Configuration", config)
    network = owner.call("GET", "/System/Configuration/network")
    network.update(AutoDiscovery=False, EnableUPnP=False)
    owner.call("POST", "/System/Configuration/network", network)
    owner.call("POST", "/Auth/Keys", query={"app": KEY_APP})
    keys = _get(owner.call("GET", "/Auth/Keys"), "Items") or []
    key = next((_get(k, "AccessToken") for k in keys if _get(k, "AppName") == KEY_APP), None)
    if not key:
        raise SetupError("Jellyfin made no key for the box")
    _write_key(key_file, key)
    owner.call("POST", "/Library/Refresh")  # media already on the box shows up now
    return user


def wait(api, seconds, log):
    """Until Jellyfin answers (it may still be starting at first boot); False after `seconds`."""
    end = time.monotonic() + seconds
    next_dot = time.monotonic() + 10
    while True:
        try:
            api._once("GET", "/System/Info/Public", None, None, 5)  # one try: this loop waits
            return True
        except SetupError:
            if time.monotonic() >= end:
                return False
        if time.monotonic() >= next_dot:
            print(".", end="", file=log, flush=True)
            next_dot += 10
        time.sleep(1)


def _folders(library, seconds):
    """The index's movies/ shows/ music/ (the library service makes them at boot) — Jellyfin
    refuses a library whose folder is missing."""
    end = time.monotonic() + seconds
    wanted = [Path(library) / folder for _, _, folder in LIBRARIES]
    while not all(p.is_dir() for p in wanted):
        if time.monotonic() >= end:
            return False
        time.sleep(1)
    return True


def main(stdin=sys.stdin, log=sys.stderr, env=os.environ):
    if stdin.isatty():  # run by hand to finish a setup: ask
        name = input("Your name on this box: ")
        password = getpass.getpass("Your password on this box: ")
    else:
        name = stdin.readline().rstrip("\n")
        password = stdin.readline().rstrip("\n")
    if not name.strip() or not password:
        print("survival-kit-media-setup: give the name and the password on two lines (stdin)", file=log)
        return 1
    waiting = float(env.get("MEDIA_WAIT", "300"))  # a first start on an old laptop is slow
    library = env.get("MEDIA_LIBRARY", "/var/lib/survival-kit/library/media")
    if not _folders(library, waiting):
        print(f"Media setup failed: the media library folders are missing ({library})", file=log)
        return 1
    api = Api(env.get("MEDIA_URL", "http://127.0.0.1:8096"))
    if not wait(api, waiting, log):
        print("Media (Jellyfin) is not answering", file=log)
        return 1
    api.deadline = time.monotonic() + float(env.get("MEDIA_DEADLINE", "300"))  # the setup itself
    try:
        user = run(api, name, password, env.get("MEDIA_KEY_FILE", "/var/lib/survival-kit/media/api-key"), library, log)
    except AlreadyDone:
        print("Media (Jellyfin) is already set up — nothing changed", file=log)
        return 2
    except SetupError as e:
        print(f"Media setup failed: {e}", file=log)
        return 1
    return 3 if user != name else 0


if __name__ == "__main__":
    sys.exit(main())
