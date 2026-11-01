"""survival-kit-media-setup — Jellyfin's one-time setup (spec 2026-11-01-media). Stdlib only.

The first-boot prompt pipes two lines into it: the owner's name and password (never on a
command line, never written to disk). It finishes Jellyfin's setup wizard with that account,
creates the three libraries (films, series, music) on the box's media index, applies the
starting offline settings and makes the box's own key for rescans. Once: after that the
settings are the owner's — nothing here runs again (a second run changes nothing, exit 2).

Exit codes: 0 done, 1 failed (one line on stderr), 2 Jellyfin was already set up.
"""

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
    """Setup failed; the message is one line for the console."""


class AlreadyDone(Exception):
    """Jellyfin's setup wizard was already completed — nothing is changed."""


def _get(d, key):
    """Jellyfin answers in PascalCase or camelCase depending on the endpoint."""
    return d.get(key, d.get(key[0].lower() + key[1:]))


class Api:
    def __init__(self, url, token=None):
        self.url = url.rstrip("/")
        self.token = token

    def call(self, method, path, body=None, query=None, timeout=30):
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
            raise SetupError(f"Jellyfin refused {method} {path} ({e.code})") from e
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
    """Set Jellyfin up once; returns the user name used. AlreadyDone / SetupError."""
    info = api.call("GET", "/System/Info/Public")
    if _get(info, "StartupWizardCompleted"):
        raise AlreadyDone()
    user = clean_user_name(name)
    if user != name:
        print(f"Media: your name there is \"{user}\" (Jellyfin allows fewer characters).", file=log)
    api.call("POST", "/Startup/Configuration",
             {"ServerName": "survival-kit", "UICulture": "en-US", "MetadataCountryCode": "US",
              "PreferredMetadataLanguage": "en"})
    api.call("GET", "/Startup/User")  # Jellyfin makes its first user here when there is none
    api.call("POST", "/Startup/User", {"Name": user, "Password": password})
    api.call("POST", "/Startup/RemoteAccess", {"EnableRemoteAccess": False, "EnableAutomaticPortMapping": False})
    api.call("POST", "/Startup/Complete")
    auth = api.call("POST", "/Users/AuthenticateByName", {"Username": user, "Pw": password})
    owner = Api(api.url, _get(auth, "AccessToken"))
    uid = _get(_get(auth, "User"), "Id")
    for title, content_type, folder in LIBRARIES:
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
            api.call("GET", "/System/Info/Public", timeout=5)
            return True
        except SetupError:
            if time.monotonic() >= end:
                return False
        if time.monotonic() >= next_dot:
            print(".", end="", file=log, flush=True)
            next_dot += 10
        time.sleep(1)


def main(stdin=sys.stdin, log=sys.stderr, env=os.environ):
    name = stdin.readline().rstrip("\n")
    password = stdin.readline().rstrip("\n")
    if not name.strip() or not password:
        print("survival-kit-media-setup: give the name and the password on two lines (stdin)", file=log)
        return 1
    api = Api(env.get("MEDIA_URL", "http://127.0.0.1:8096"))
    if not wait(api, float(env.get("MEDIA_WAIT", "180")), log):
        print("Media (Jellyfin) is not answering", file=log)
        return 1
    try:
        run(api, name, password, env.get("MEDIA_KEY_FILE", "/var/lib/survival-kit/media/api-key"),
            env.get("MEDIA_LIBRARY", "/var/lib/survival-kit/library/media"), log)
    except AlreadyDone:
        print("Media (Jellyfin) is already set up — nothing changed", file=log)
        return 2
    except SetupError as e:
        print(f"Media setup failed: {e}", file=log)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
