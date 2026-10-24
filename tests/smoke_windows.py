"""Windows smoke test, run by CI on a Windows machine: real network, real yt-dlp and ffmpeg.
Not part of the unit tests. Checks the host's framing, its tool install, the analysis and a short download."""
import glob, json, os, struct, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host"))
import m3u8_host as host

STREAM = "https://devstreaming-cdn.apple.com/videos/streaming/examples/bipbop_4x3/bipbop_4x3_variant.m3u8"


def call(msg):
    data = json.dumps(msg).encode()
    out = subprocess.run([sys.executable, host.__file__], input=struct.pack("<I", len(data)) + data,
                         capture_output=True, timeout=900)
    assert out.stdout, out.stderr.decode(errors="replace")
    return json.loads(out.stdout[4:4 + struct.unpack("<I", out.stdout[:4])[0]])


info = call({"action": "formats", "url": STREAM})
assert info.get("formats"), info
assert os.path.exists(host.YTDLP), "yt-dlp.exe was not installed next to the host"
print("formats:", [(f["id"], f["height"]) for f in info["formats"]], "duration:", info["duration"])

# The download command the host would start in a new console, run here with a 6-second section
started = {}
host.start_windows = lambda cmd, dirs, folder: started.update(cmd=cmd, folder=folder) or {"ok": True}
host.FFPROBE, host.FFMPEG = (host.shutil.which(n, path=host.ENV["PATH"]) for n in ("ffprobe", "ffmpeg"))
host.download(STREAM, info["formats"][-1]["id"], ["Séries", "Test (2026)", "Season 01", "Test S01E01"], None)
cmd = started["cmd"]
cmd[cmd.index("--"):cmd.index("--")] = ["--download-sections", "*0-6"]
subprocess.run(cmd, env=host.ENV, check=True, timeout=600)
files = glob.glob(os.path.join(started["folder"], "*.mp4"))
assert files and os.path.getsize(files[0]) > 10_000, files
print("downloaded:", files[0], os.path.getsize(files[0]), "bytes")
