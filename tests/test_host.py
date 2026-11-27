"""Offline tests for the native host: URL checks, Jellyfin paths, the download script, playlist parsing.

Run: python3 -m unittest discover -s tests -t .
Nothing is downloaded and no Terminal is opened: subprocess and network calls are replaced.
"""

import importlib.util
import io
import json
import os
import shlex
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Imported before sys.platform is patched: some standard modules read it at import time
import concurrent.futures, platform, shutil, subprocess, urllib.request  # noqa: E401,F401

HOST = Path(__file__).resolve().parents[1] / "host" / "m3u8_host.py"


def load(platform, env=None, which=None):
    """A fresh copy of the host as it starts on `platform` (sys.platform is patched), whatever this OS is."""
    spec = importlib.util.spec_from_file_location("m3u8_host", HOST)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.object(sys, "platform", platform), mock.patch.dict(os.environ, env or {}), \
         mock.patch("shutil.which", which or (lambda name, path=None: None)):
        if env is not None and "XDG_VIDEOS_DIR" not in env:
            os.environ.pop("XDG_VIDEOS_DIR", None)
        spec.loader.exec_module(module)
    return module


# Most tests describe the macOS host (the .command file for Terminal), on any OS
host = load("darwin")


class Urls(unittest.TestCase):
    def test_only_web_urls_reach_yt_dlp(self):
        self.assertEqual(host.checked("https://cdn.example/x.m3u8"), "https://cdn.example/x.m3u8")
        for bad in ("file:///etc/passwd", "-o/tmp/x", "javascript:alert(1)", None, 3):
            with self.assertRaises(ValueError):
                host.checked(bad)

    def test_fetch_refuses_other_schemes(self):
        with self.assertRaises(ValueError):
            host.fetch("file:///etc/passwd", None)
        self.assertIsNone(host.playlist_duration("file:///etc/passwd", None))


class Names(unittest.TestCase):
    def test_clean_drops_characters_finder_or_yt_dlp_dislike(self):
        self.assertEqual(host.clean('Dune: Part / Two?  "VF"'), "Dune Part Two VF")
        self.assertEqual(host.clean(None), "")


class Download(unittest.TestCase):
    """The .command file written for Terminal: where it saves, and what it runs."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        patches = [mock.patch.object(host, "ROOT", self.root),
                   mock.patch.object(host.subprocess, "run")]
        self.run = None
        for p in patches:
            started = p.start()
            self.addCleanup(p.stop)
            if p.attribute == "run":
                self.run = started

    def script(self, **kw):
        args = {"url": "https://cdn.example/master.m3u8", "fmt": None, "path": ["Films", "Dune"], "referer": None}
        args.update(kw)
        self.assertEqual(host.download(args["url"], args["fmt"], args["path"], args["referer"],
                                       kw.get("audio"), kw.get("subs")), {"ok": True})
        job = self.run.call_args_list[-1].args[0][-1]          # open -a Terminal <job>
        text = Path(job).read_text()
        os.unlink(job)
        cmd_line = next(l for l in text.splitlines() if l.startswith("/") and "yt-dlp" in l)
        return shlex.split(cmd_line.split(" && ")[0])

    def out(self, cmd):
        return cmd[cmd.index("-o") + 1]

    def test_a_film_lands_in_films(self):
        cmd = self.script()
        self.assertEqual(self.out(cmd), os.path.join(self.root, "Films", "Dune.%(ext)s"))
        self.assertEqual(cmd[-2:], ["--", "https://cdn.example/master.m3u8"])

    def test_an_episode_lands_in_its_series_and_season(self):
        cmd = self.script(path=["Séries", "Dark (2017)", "Season 03", "Dark S03E08 (VO)"])
        self.assertEqual(self.out(cmd), os.path.join(self.root, "Séries", "Dark (2017)", "Season 03", "Dark S03E08 (VO).%(ext)s"))

    def test_the_path_cannot_climb_out_of_the_films_folder(self):
        cmd = self.script(path=["..", "../..", "/etc", "x/../../y", "evil"])
        out = os.path.realpath(self.out(cmd).replace("%(ext)s", "mp4"))
        self.assertTrue(out.startswith(os.path.realpath(self.root) + os.sep), out)

    def test_a_percent_in_the_name_is_not_a_yt_dlp_template(self):
        cmd = self.script(path=["Films", "100%(id)s"])
        self.assertEqual(self.out(cmd), os.path.join(self.root, "Films", "100%%(id)s.%(ext)s"))

    def test_no_name_falls_back_to_the_video_title(self):
        self.assertTrue(self.out(self.script(path=["Films", ""])).endswith("/Films/%(title)s.%(ext)s"))

    def test_format_audio_and_subtitles_selection(self):
        cmd = self.script(fmt="720", audio="aud-fr", subs=["fr", "en"])
        self.assertEqual(cmd[cmd.index("-f") + 1], "720+aud-fr/720")
        self.assertEqual(cmd[cmd.index("--sub-langs") + 1], "fr,en")
        self.assertIn("--embed-subs", cmd)
        self.assertEqual(self.script()[2], "bv*+ba/b")

    def test_a_bad_url_writes_no_script(self):
        with self.assertRaises(ValueError):
            host.download("file:///etc/passwd", None, ["Films", "x"], None)
        self.assertFalse(self.run.called)


class Series(unittest.TestCase):
    def test_lists_only_folders(self):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "Séries", "Dark"))
        os.makedirs(os.path.join(root, "Séries", "Arcane (2021)"))
        Path(root, "Séries", "notes.txt").write_text("x")
        with mock.patch.object(host, "ROOT", root):
            self.assertEqual(host.series(), {"series": ["Arcane (2021)", "Dark"]})
        with mock.patch.object(host, "ROOT", os.path.join(root, "nope")):
            self.assertEqual(host.series(), {"series": []})


PLAYLIST = """#EXTM3U
#EXT-X-TARGETDURATION:6
#EXTINF:6.0,
seg0.ts
#EXTINF:6.0,
seg1.ts
#EXTINF:4.5,
seg2.ts
#EXT-X-ENDLIST
"""


class Playlists(unittest.TestCase):
    def test_duration_is_the_sum_of_extinf(self):
        fake = mock.MagicMock()
        fake.read.return_value = PLAYLIST.encode()
        with mock.patch.object(host.urllib.request, "urlopen", return_value=fake):
            self.assertEqual(host.playlist_duration("https://cdn.example/a.m3u8", None), 16)

    def test_probe_measures_a_middle_segment(self):
        seg = b"\0" * 750_000  # 6 s segment of 750 kB = 1000 kbit/s
        def fetch(url, referer, limit=None):
            return PLAYLIST.encode() if url.endswith(".m3u8") else seg
        with mock.patch.object(host, "fetch", side_effect=fetch) as f, \
             mock.patch.object(host, "ffprobe_video", return_value={"width": 1280, "height": 720, "codec_name": "h264"}):
            got = host.probe("https://cdn.example/v/720.m3u8", None)
        self.assertEqual(got, {"width": 1280, "height": 720, "vcodec": "h264", "kbps": 1000})
        self.assertEqual(f.call_args_list[1].args[0], "https://cdn.example/v/seg1.ts")

    def test_probe_skips_a_master_playlist(self):
        with mock.patch.object(host, "fetch", return_value=b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nlow.m3u8\n"):
            self.assertIsNone(host.probe("https://cdn.example/master.m3u8", None))


class Formats(unittest.TestCase):
    def yt(self, data):
        out = mock.MagicMock(returncode=0, stdout=json.dumps(data), stderr="")
        return mock.patch.object(host.subprocess, "run", return_value=out)

    def test_video_formats_sorted_best_first_with_estimated_size(self):
        data = {"title": "T", "duration": 100, "formats": [
            {"format_id": "a", "vcodec": "avc1.64", "acodec": "none", "height": 480, "tbr": 800},
            {"format_id": "b", "vcodec": "avc1.64", "acodec": "mp4a", "height": 1080, "tbr": 4000},
            {"format_id": "fr", "vcodec": "none", "acodec": "mp4a", "language": "fr", "tbr": 128}]}
        with self.yt(data):
            got = host.formats("https://cdn.example/master.m3u8", "https://site.example/")
        self.assertEqual([f["id"] for f in got["formats"]], ["b", "a"])
        self.assertEqual(got["formats"][0]["size"], 4000 * 1000 // 8 * 100)
        self.assertTrue(got["formats"][0]["muxedAudio"])
        self.assertEqual(got["formats"][0]["vcodec"], "avc1")
        self.assertEqual([a["id"] for a in got["audios"]], ["fr"])

    def test_yt_dlp_error_is_returned_as_its_last_line(self):
        out = mock.MagicMock(returncode=1, stdout="", stderr="WARNING x\nERROR: 403 Forbidden")
        with mock.patch.object(host.subprocess, "run", return_value=out):
            self.assertEqual(host.formats("https://cdn.example/a.m3u8", None), {"error": "ERROR: 403 Forbidden"})


class Messaging(unittest.TestCase):
    """Chrome's native messaging framing: 4-byte little-endian length, then JSON."""

    def test_round_trip(self):
        payload = json.dumps({"action": "series"}).encode()
        stdin = io.BytesIO(struct.pack("<I", len(payload)) + payload)
        stdout = io.BytesIO()
        with mock.patch.object(host.sys, "stdin", mock.MagicMock(buffer=stdin)), \
             mock.patch.object(host.sys, "stdout", mock.MagicMock(buffer=stdout)), \
             mock.patch.object(host, "series", return_value={"series": ["Dark"]}):
            host.main()
        raw = stdout.getvalue()
        self.assertEqual(json.loads(raw[4:]), {"series": ["Dark"]})
        self.assertEqual(struct.unpack("<I", raw[:4])[0], len(raw) - 4)

    def test_unknown_action_and_errors_are_answered_not_raised(self):
        for msg, expected in (({"action": "nope"}, {"error": "action inconnue"}),
                              ({"action": "formats"}, None)):
            payload = json.dumps(msg).encode()
            stdout = io.BytesIO()
            with mock.patch.object(host.sys, "stdin", mock.MagicMock(buffer=io.BytesIO(struct.pack("<I", len(payload)) + payload))), \
                 mock.patch.object(host.sys, "stdout", mock.MagicMock(buffer=stdout)):
                host.main()
            answer = json.loads(stdout.getvalue()[4:])
            self.assertIn("error", answer)
            if expected:
                self.assertEqual(answer, expected)


def home_env(home):
    # expanduser reads HOME on POSIX and USERPROFILE on Windows
    return {"HOME": home, "USERPROFILE": home}


class Linux(unittest.TestCase):
    """The Linux branch: tools, download folder, how a download starts, manifests. Runs on any OS."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, home_env(self.home))
        env.start()
        self.addCleanup(env.stop)

    def linux(self, which=None, **env):
        return load("linux", {**home_env(self.home), **env}, which)

    def test_yt_dlp_next_to_the_host_and_ffmpeg_from_the_path(self):
        found = {"ffprobe": "/usr/bin/ffprobe"}
        h = self.linux(which=lambda name, path=None: found.get(name), PATH="/usr/bin")
        self.assertTrue(h.LINUX)
        self.assertFalse(h.WINDOWS)
        self.assertEqual(h.YTDLP, os.path.join(HOST.parent, "bin", "yt-dlp"))
        self.assertEqual(h.FFPROBE, "/usr/bin/ffprobe")
        self.assertIsNone(h.FFMPEG)
        self.assertEqual(h.ENV["PATH"].split(os.pathsep)[:2], [os.path.join(HOST.parent, "bin"), "/usr/bin"])
        self.assertEqual(self.linux().FFPROBE, "ffprobe")

    def test_official_binary_for_the_processor(self):
        base = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
        self.assertEqual(host.ytdlp_linux_url("x86_64"), base + "yt-dlp_linux")
        self.assertEqual(host.ytdlp_linux_url("aarch64"), base + "yt-dlp_linux_aarch64")
        self.assertEqual(host.ytdlp_linux_url("riscv64"), base + "yt-dlp")

    def test_yt_dlp_updates_weekly(self):
        h = self.linux()
        ytdlp = Path(self.home, "yt-dlp")
        ytdlp.write_text("x")
        with mock.patch.object(h, "YTDLP", str(ytdlp)):
            self.assertFalse(h.update_due())
            os.utime(ytdlp, (0, 0))
            self.assertTrue(h.update_due())
        self.assertFalse(host.update_due())  # macOS: Homebrew updates it

    def test_download_folder(self):
        self.assertEqual(self.linux().ROOT, os.path.join(self.home, "Videos", "Films"))
        videos = os.path.join(self.home, "Vidéos")
        self.assertEqual(self.linux(XDG_VIDEOS_DIR=videos).ROOT, os.path.join(videos, "Films"))
        os.makedirs(os.path.join(self.home, "Documents", "Films"))
        self.assertEqual(self.linux(XDG_VIDEOS_DIR=videos).ROOT, os.path.join(self.home, "Documents", "Films"))

    def test_macos_and_windows_folders_do_not_change(self):
        self.assertEqual(load("darwin", home_env(self.home)).ROOT, os.path.join(self.home, "Movies", "Films"))

    def start(self, which):
        h = self.linux(which=which)
        root = tempfile.mkdtemp()
        with mock.patch.object(h, "ROOT", root), mock.patch.object(h.subprocess, "Popen") as popen, \
             mock.patch.object(h.shutil, "which", side_effect=which):
            self.assertEqual(h.download("https://cdn.example/a.m3u8", "720", ["Films", "Dune"], None), {"ok": True})
        args, kw = popen.call_args
        job = Path(args[0][-1])
        text = job.read_text()
        os.unlink(job)
        self.assertTrue(text.startswith("#!/bin/bash\n"))
        self.assertIn("trap : INT", text)
        line = next(l.strip() for l in text.splitlines() if l.strip().startswith("if " + shlex.quote(h.YTDLP)))
        cmd = shlex.split(line[3:].rsplit(";", 1)[0])
        self.assertEqual(cmd[cmd.index("-o") + 1], os.path.join(root, "Films", "Dune.%(ext)s"))
        self.assertEqual(cmd[-2:], ["--", "https://cdn.example/a.m3u8"])
        self.assertTrue(kw["start_new_session"])
        self.assertIsNot(kw["stdout"], None)  # never Chrome's channel
        return args[0], kw

    def test_a_download_runs_in_the_first_terminal_found(self):
        terms = {"x-terminal-emulator": "/usr/bin/x-terminal-emulator", "gnome-terminal": "/usr/bin/gnome-terminal",
                 "konsole": "/usr/bin/konsole"}
        argv, _ = self.start(lambda name, path=None: terms.get(name))
        self.assertEqual(argv[:3], ["/usr/bin/x-terminal-emulator", "-e", "bash"])
        del terms["x-terminal-emulator"]
        self.assertEqual(self.start(lambda name, path=None: terms.get(name))[0][:3], ["/usr/bin/gnome-terminal", "--", "bash"])
        del terms["gnome-terminal"]
        self.assertEqual(self.start(lambda name, path=None: terms.get(name))[0][:3], ["/usr/bin/konsole", "-e", "bash"])

    def test_without_a_terminal_it_runs_in_the_background_with_a_log(self):
        argv, kw = self.start(lambda name, path=None: None)
        self.assertEqual(argv[0], "bash")
        self.assertEqual(kw["stdout"].name, os.path.join(self.home, ".cache", "m3u8-sniffer", "Dune.log"))

    def test_manifests_only_for_installed_browsers(self):
        installed = {"google-chrome-stable"}
        h = self.linux()
        with mock.patch.object(h.shutil, "which", lambda name, path=None: name if name in installed else None):
            self.assertEqual(h.manifest_dirs(), [os.path.join(self.home, ".config", "google-chrome", "NativeMessagingHosts")])
            installed = {"google-chrome", "chromium-browser"}
            self.assertEqual(h.manifest_dirs(), [os.path.join(self.home, ".config", d, "NativeMessagingHosts")
                                                 for d in ("google-chrome", "chromium")])
            installed = set()
            self.assertEqual(h.manifest_dirs(), [])

    def test_install_writes_the_manifest_for_chrome(self):
        h = self.linux()
        with mock.patch.object(h, "install_tools"), mock.patch.object(h.os, "chmod"), \
             mock.patch.object(h.shutil, "which", lambda name, path=None: name if name == "chromium" else None), \
             mock.patch("builtins.print"):
            self.assertEqual(h.install_linux(), 0)
        d = Path(self.home, ".config", "chromium", "NativeMessagingHosts")
        manifest = json.loads((d / "dev.byelior.m3u8.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "dev.byelior.m3u8")
        self.assertEqual(manifest["path"], str(HOST))
        self.assertEqual(manifest["allowed_origins"], ["chrome-extension://iklhldaffdlkmofoamlacnkcicnnigkf/"])
        self.assertFalse(Path(self.home, ".config", "google-chrome").exists())

    def test_install_fails_without_a_browser(self):
        h = self.linux()
        with mock.patch.object(h, "install_tools"), mock.patch.object(h.os, "chmod"), mock.patch("builtins.print"), \
             mock.patch.object(h.shutil, "which", lambda name, path=None: None):
            self.assertEqual(h.install_linux(), 1)
        self.assertFalse(Path(self.home, ".config").exists())


if __name__ == "__main__":
    unittest.main()
