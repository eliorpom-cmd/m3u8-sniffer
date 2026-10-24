#!/usr/bin/env python3
"""Chrome native messaging host: lists stream qualities and starts downloads in a terminal window.
macOS (Homebrew tools, Terminal) and Windows (winget tools, console window)."""
import json, os, re, shlex, shutil, struct, subprocess, sys, tempfile, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

WINDOWS = sys.platform == "win32"
if WINDOWS:
    import winreg

    def registry_path():
        """PATH as saved in the registry: Chrome keeps the one it started with, older than any install since."""
        parts = []
        for root, key in ((winreg.HKEY_CURRENT_USER, "Environment"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
            try:
                with winreg.OpenKey(root, key) as k:
                    parts.append(os.path.expandvars(winreg.QueryValueEx(k, "Path")[0]))
            except OSError:
                pass
        return os.pathsep.join(parts)

    # yt-dlp.exe lives next to the host so it can update itself; ffmpeg comes from winget (per-user or machine links)
    BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
    LINKS = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links"),
             os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "WinGet", "Links")]
    ENV = {**os.environ, "PATH": os.pathsep.join([BIN, *LINKS, registry_path(), os.environ.get("PATH", "")])}
    YTDLP = os.path.join(BIN, "yt-dlp.exe")
    FFPROBE, FFMPEG = (shutil.which(n, path=ENV["PATH"]) or n + ".exe" for n in ("ffprobe", "ffmpeg"))
else:
    # Chrome gives the host a minimal PATH: Homebrew's folder, Apple Silicon or Intel
    BREW = "/opt/homebrew/bin" if os.path.isdir("/opt/homebrew/bin") else "/usr/local/bin"
    YTDLP = f"{BREW}/yt-dlp"
    FFPROBE = f"{BREW}/ffprobe"
    FFMPEG = None
    ENV = {**os.environ, "PATH": f"{BREW}:/usr/bin:/bin"}

YTDLP_EXE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"


@contextmanager
def tools_lock():
    # The popup analyses every stream at once, one host process each: only one may install
    with open(os.path.join(tempfile.gettempdir(), "m3u8-sniffer-tools.lock"), "a+") as f:
        if WINDOWS:
            import msvcrt
            while True:
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)  # gives up after 10 s: try again
                    break
                except OSError:
                    pass
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if WINDOWS:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


def update_due():
    return WINDOWS and os.path.exists(YTDLP) and time.time() - os.path.getmtime(YTDLP) > 7 * 86400


def ensure_tools():
    """Install yt-dlp and ffmpeg when missing, so the extension works on a fresh machine.
    Never fatal: when an install fails, the yt-dlp or ffprobe call that follows reports it."""
    if os.path.exists(YTDLP) and shutil.which(FFPROBE, path=ENV["PATH"]) and not update_due():
        return
    try:
        with tools_lock():
            install_tools()
    except Exception:
        pass


def install_tools():
    global FFPROBE, FFMPEG
    if not WINDOWS:
        missing = [n for n, p in (("yt-dlp", YTDLP), ("ffmpeg", FFPROBE)) if not os.path.exists(p)]
        if missing:
            subprocess.run([f"{BREW}/brew", "install", *missing], env=ENV, capture_output=True, timeout=900)
        return
    os.makedirs(BIN, exist_ok=True)
    if not os.path.exists(YTDLP):
        with urllib.request.urlopen(YTDLP_EXE, timeout=120) as r, open(YTDLP + ".part", "wb") as f:
            shutil.copyfileobj(r, f)
        os.replace(YTDLP + ".part", YTDLP)
    elif update_due():
        # Sites change often and old yt-dlp versions stop working: update once a week.
        # The date moves first, so a failed update is not retried on every call.
        os.utime(YTDLP)
        subprocess.run([YTDLP, "-U"], env=ENV, capture_output=True, timeout=60)
    if not shutil.which("ffprobe", path=ENV["PATH"]):
        subprocess.run(["winget", "install", "-e", "--id", "Gyan.FFmpeg", "--silent",
                        "--accept-source-agreements", "--accept-package-agreements"],
                       env=ENV, capture_output=True, timeout=900)
        ENV["PATH"] = os.pathsep.join([BIN, *LINKS, registry_path(), os.environ.get("PATH", "")])
        FFPROBE, FFMPEG = (shutil.which(n, path=ENV["PATH"]) or n + ".exe" for n in ("ffprobe", "ffmpeg"))


def read_msg():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        sys.exit(0)
    return json.loads(sys.stdin.buffer.read(struct.unpack("<I", raw)[0]))


def send(obj):
    data = json.dumps(obj).encode()
    sys.stdout.buffer.write(struct.pack("<I", len(data)) + data)
    sys.stdout.buffer.flush()


def checked(url):
    # The URL comes from whatever the page loaded: only plain web URLs, and
    # always after "--" below, so a value starting with "-" is never an option.
    if not isinstance(url, str) or not url.lower().startswith(("http://", "https://")):
        raise ValueError("URL refusée (http ou https seulement)")
    return url


def playlist_duration(url, referer):
    """Sum the EXTINF durations of a media playlist (yt-dlp gives none for HLS masters)."""
    if not str(url).lower().startswith(("http://", "https://")):
        return None  # urllib would also open file:// and others
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **({"Referer": referer} if referer else {})})
    try:
        text = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "replace")
    except Exception:
        return None
    total = sum(float(m) for m in re.findall(r"#EXTINF:([\d.]+)", text))
    return round(total) or None


def fetch(url, referer, limit=None):
    if not str(url).lower().startswith(("http://", "https://")):
        raise ValueError("URL refusée")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", **({"Referer": referer} if referer else {})})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read(limit) if limit else r.read()


def ffprobe_video(target, referer):
    cmd = [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name",
           "-of", "json", "-extension_picky", "0"]
    if referer and target.startswith("http"):
        # The referer is the page URL: no line break may slip in an extra header
        referer = re.sub(r"[\r\n]", "", referer)
        cmd += ["-headers", f"Referer: {referer}\r\nUser-Agent: Mozilla/5.0\r\n"]
    out = subprocess.run(cmd + [target], capture_output=True, text=True, env=ENV, timeout=30)
    streams = json.loads(out.stdout or "{}").get("streams") or []
    return streams[0] if streams and streams[0].get("height") else None


def probe(url, referer):
    """Measure the real resolution and bitrate of a media playlist from one of its segments,
    whatever the master declares (many servers give no RESOLUTION or BANDWIDTH at all)."""
    try:
        text = fetch(url, referer).decode("utf-8", "replace")
        if "#EXT-X-STREAM-INF" in text:
            return None
        segs, dur = [], None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#EXTINF:"):
                dur = float(re.match(r"#EXTINF:([\d.]+)", line).group(1))
            elif line and not line.startswith("#") and dur:
                segs.append((urllib.parse.urljoin(url, line), dur))
                dur = None
        if not segs:
            return None
        # A segment from the middle: the first ones are sometimes a low-quality intro or an ad
        seg_url, seg_dur = segs[len(segs) // 2]
        data = fetch(seg_url, referer, 40_000_000)
        kbps = int(len(data) * 8 / seg_dur / 1000) if seg_dur else None
        video = None
        # Encrypted or fMP4 segments can't be read alone: let ffprobe open the playlist instead
        if not re.search(r"#EXT-X-KEY:(?!.*METHOD=NONE)|#EXT-X-MAP", text):
            # delete=False: Windows can't open a temp file a second time while it is open
            with tempfile.NamedTemporaryFile(suffix=".ts", delete=False) as tmp:
                tmp.write(data)
            try:
                video = ffprobe_video(tmp.name, None)
            finally:
                os.unlink(tmp.name)
        video = video or ffprobe_video(url, referer)
        if not video:
            return {"kbps": kbps} if kbps else None
        return {"width": video["width"], "height": video["height"], "vcodec": video.get("codec_name"), "kbps": kbps}
    except Exception:
        return None


def formats(url, referer):
    cmd = [YTDLP, "-J", "--no-warnings"]
    if referer:
        cmd += ["--referer", referer]
    cmd += ["--", checked(url)]
    out = subprocess.run(cmd, capture_output=True, text=True, env=ENV, timeout=60)
    if out.returncode != 0:
        return {"error": out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "yt-dlp a échoué"}
    d = json.loads(out.stdout)
    fs = [f for f in d.get("formats", []) if f.get("vcodec") != "none"]
    fs.sort(key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)
    # Audio-only renditions: one per language in multi-language HLS masters
    auds = [f for f in d.get("formats", []) if f.get("vcodec") == "none" and f.get("acodec") != "none"]
    duration = d.get("duration") or (fs and playlist_duration(fs[0]["url"], referer)) or None

    # Variants without a declared resolution: measure them (in parallel, at most 6)
    blind = [f for f in fs if not f.get("height") and str(f.get("url", "")).startswith("http")][:6]
    if blind:
        with ThreadPoolExecutor(len(blind)) as pool:
            for f, m in zip(blind, pool.map(lambda f: probe(f["url"], referer), blind)):
                if m:
                    f["measured"] = True
                    f["height"] = m.get("height") or f.get("height")
                    f["width"] = m.get("width") or f.get("width")
                    f["tbr"] = f.get("tbr") or m.get("kbps")
                    if m.get("vcodec") and not f.get("vcodec"):
                        f["vcodec"] = {"h264": "avc1", "hevc": "hvc1"}.get(m["vcodec"], m["vcodec"])
        fs.sort(key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)

    def size(f):
        b = f.get("filesize") or f.get("filesize_approx")
        if not b and duration and f.get("tbr"):
            b = f["tbr"] * 1000 / 8 * duration
        return int(b) if b else None

    subs = [{"lang": lang, "name": (tracks[0].get("name") if tracks else None) or lang}
            for lang, tracks in (d.get("subtitles") or {}).items()]
    return {"title": d.get("title"), "duration": duration, "subtitles": subs, "formats": [
        {"id": f["format_id"], "height": f.get("height"), "width": f.get("width"), "kbps": int(f.get("tbr") or 0),
         "fps": f.get("fps"), "vcodec": (f.get("vcodec") or "").split(".")[0], "size": size(f),
         "lang": f.get("language"), "measured": bool(f.get("measured")), "muxedAudio": f.get("acodec") not in (None, "none")} for f in fs],
        "audios": [{"id": f["format_id"], "lang": f.get("language"), "channels": f.get("audio_channels"),
                    "name": f.get("format_note") or f.get("format_id"), "size": size(f)} for f in auds]}


# Jellyfin layout under ROOT: movies in Films/, episodes in Séries/<Show (Year)>/Season NN/
# ~/Documents/Films when it already exists (the author's Jellyfin libraries), otherwise the
# system's video folder: Videos on Windows (Documents is often synced by OneDrive), Movies on macOS
ROOT = (os.path.expanduser("~/Documents/Films") if os.path.isdir(os.path.expanduser("~/Documents/Films"))
        else os.path.expanduser("~/Videos/Films" if WINDOWS else "~/Movies/Films"))


def series():
    d = os.path.join(ROOT, "Séries")
    names = sorted(x for x in os.listdir(d) if os.path.isdir(os.path.join(d, x))) if os.path.isdir(d) else []
    return {"series": names}


def clean(part):
    part = re.sub(r"\s+", " ", re.sub(r'[/:*?"<>|\\]', "", part or "")).strip()
    # Windows drops trailing dots and spaces from names, which would split a series folder in two
    return part.rstrip(". ") if WINDOWS else part


def download(url, fmt, path, referer, audio=None, subs=None):
    # path = [folder, ..., file name] relative to ROOT; dot-only folders are dropped so it cannot escape ROOT
    *dirs, name = path or ["Films", ""]
    dirs = [d for d in map(clean, dirs) if d.strip(".")] or ["Films"]
    name = clean(name)
    folder = os.path.join(ROOT, *dirs)
    # "%" starts a yt-dlp output template: a title like "100%(x)s" must stay literal
    out = os.path.join(folder.replace("%", "%%"), f"{name.replace('%', '%%') or '%(title)s'}.%(ext)s")
    aud = audio or "bestaudio"
    sel = f"{fmt}+{aud}/{fmt}" if fmt else f"bv*+{audio}/b" if audio else "bv*+ba/b"
    cmd = [YTDLP, "-f", sel,
           "--merge-output-format", "mp4", "-N", "8", "-o", out]
    if referer:
        cmd += ["--referer", referer]
    if subs:
        cmd += ["--write-subs", "--sub-langs", ",".join(subs), "--embed-subs"]
    if FFMPEG:
        cmd += ["--ffmpeg-location", FFMPEG]
    cmd += ["--", checked(url)]
    if WINDOWS:
        return start_windows(cmd, dirs, folder)
    shell = " ".join(shlex.quote(c) for c in cmd)
    # A .command file opened by Launch Services runs in its own Terminal window,
    # independent of this host process (Chrome kills the host once it replies).
    job = tempfile.NamedTemporaryFile("w", suffix=".command", delete=False, prefix="m3u8-")
    job.write(f"""#!/bin/zsh
clear
echo "⬇️  Téléchargement en cours — ctrl+C pour annuler"
echo {shlex.quote("📁 " + " › ".join(dirs))}
echo
{shell} && {{ echo; echo "✅ Terminé"; open {shlex.quote(folder)}; }} || {{ echo; echo "⛔️ Arrêté"; }}
rm -f {shlex.quote(job.name)}
""")
    job.close()
    os.chmod(job.name, 0o755)
    # Files written by Chrome's child processes are quarantined; Gatekeeper would block the script
    subprocess.run(["xattr", "-d", "com.apple.quarantine", job.name], capture_output=True)
    subprocess.run(["open", "-a", "Terminal", job.name], env=ENV)
    return {"ok": True}


def start_windows(cmd, dirs, folder):
    # The same file runs again in its own console window ("--run"), so the download
    # outlives this host and no command line has to go through cmd.exe quoting.
    job = json.dumps({"cmd": cmd, "dirs": dirs, "folder": folder})
    flags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
    args = [sys.executable, os.path.abspath(__file__), "--run", job]
    try:
        # Leave Chrome's job object if it has one, or closing the host would kill the download
        subprocess.Popen(args, env=ENV, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB)
    except OSError:
        subprocess.Popen(args, env=ENV, creationflags=flags)
    return {"ok": True}


def run_windows(job):
    job = json.loads(job)
    os.system("title M3U8 Sniffer")
    print("Téléchargement en cours — ctrl+C pour annuler")
    print("Dossier : " + " > ".join(job["dirs"]))
    print()
    try:
        ok = subprocess.run(job["cmd"], env=ENV).returncode == 0
    except KeyboardInterrupt:
        ok = False
    print()
    if ok:
        print("Terminé")
        os.startfile(job["folder"])
    else:
        print("Arrêté")
    input("Appuie sur Entrée pour fermer cette fenêtre.")


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--run":
        return run_windows(sys.argv[2])
    msg = read_msg()
    try:
        if msg.get("action") in ("formats", "download"):
            ensure_tools()
        if msg.get("action") == "formats":
            send(formats(msg["url"], msg.get("referer")))
        elif msg.get("action") == "download":
            send(download(msg["url"], msg.get("format"), msg.get("path") or ["Films", msg.get("name")], msg.get("referer"),
                          msg.get("audio"), msg.get("subs")))
        elif msg.get("action") == "series":
            send(series())
        else:
            send({"error": "action inconnue"})
    except Exception as e:
        send({"error": str(e)})


# Chrome runs this file as a script; tests import it without reading stdin.
if __name__ == "__main__":
    main()
