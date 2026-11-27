"""Linux smoke test, run by CI on Ubuntu after install-host-linux.sh: real network, real yt-dlp and ffmpeg.
Not part of the unit tests. Checks the installer's manifests, the host's framing, the analysis and a short
download started the way the host starts one when there is no terminal (in the background, with a log)."""
import glob, json, os, shutil, struct, subprocess, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "host"))
import m3u8_host as host

STREAM = "https://devstreaming-cdn.apple.com/videos/streaming/examples/bipbop_4x3/bipbop_4x3_variant.m3u8"


def call(msg):
    data = json.dumps(msg).encode()
    # Run the way Chrome does: the host file itself, through its shebang
    out = subprocess.run([host.__file__], input=struct.pack("<I", len(data)) + data, capture_output=True, timeout=900)
    assert out.stdout, out.stderr.decode(errors="replace")
    return json.loads(out.stdout[4:4 + struct.unpack("<I", out.stdout[:4])[0]])


# The installer registered the host for each installed browser, and only for those
registered = 0
for folder, commands in host.BROWSERS:
    manifest = os.path.expanduser(f"~/.config/{folder}/NativeMessagingHosts/{host.MANIFEST}")
    installed = any(shutil.which(c) for c in commands)
    assert os.path.exists(manifest) == installed, (folder, installed)
    if installed:
        with open(manifest, encoding="utf-8") as f:
            assert json.load(f)["path"] == os.path.abspath(host.__file__)
        registered += 1
        print("manifest:", manifest)
assert registered, "neither Google Chrome nor Chromium found"
assert os.access(host.YTDLP, os.X_OK), "yt-dlp was not installed next to the host"

info = call({"action": "formats", "url": STREAM})
assert info.get("formats"), info
print("formats:", [(f["id"], f["height"]) for f in info["formats"]], "duration:", info["duration"])

# The host's download, cut to a 6-second section, then started by the host itself in the background
start_linux, started = host.start_linux, {}
host.start_linux = lambda cmd, dirs, folder, name: started.update(cmd=cmd, dirs=dirs, folder=folder, name=name) or {"ok": True}
host.download(STREAM, info["formats"][-1]["id"], ["Séries", "Test (2026)", "Season 01", "Test S01E01"], None)
cmd = started["cmd"]
cmd[cmd.index("--"):cmd.index("--")] = ["--download-sections", "*0-6"]
host.terminal = lambda: None
assert start_linux(cmd, started["dirs"], started["folder"], started["name"]) == {"ok": True}

log = os.path.expanduser("~/.cache/m3u8-sniffer/Test S01E01.log")
deadline = time.time() + 600
while time.time() < deadline:
    text = open(log, encoding="utf-8", errors="replace").read() if os.path.exists(log) else ""
    if "Terminé" in text or "Arrêté" in text:
        break
    time.sleep(2)
print(text)
assert "Terminé" in text, "the download did not finish"
files = glob.glob(os.path.join(started["folder"], "*.mp4"))
assert files and os.path.getsize(files[0]) > 10_000, files
print("downloaded:", files[0], os.path.getsize(files[0]), "bytes")
