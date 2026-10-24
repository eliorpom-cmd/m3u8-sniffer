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
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HOST = Path(__file__).resolve().parents[1] / "host" / "m3u8_host.py"
spec = importlib.util.spec_from_file_location("m3u8_host", HOST)
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


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


if __name__ == "__main__":
    unittest.main()
