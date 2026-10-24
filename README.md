# M3U8 Sniffer

A Chrome extension that finds the `.m3u8` (HLS) link of a video playing in a tab and downloads it in one click,
in the best quality, with the audio track and subtitles you choose. Works on macOS and Windows.

> **French interface.** The popup and the installers are in French. Files are sorted for
> [Jellyfin](https://jellyfin.org): movies in one folder, episodes by show and season.

Download only what you have the right to download.

## Install

The extension isn't on the Chrome Web Store: a downloader needs a small program on your computer
([yt-dlp](https://github.com/yt-dlp/yt-dlp) and ffmpeg), which store extensions can't install. You load it in
Chrome's developer mode instead, which takes a minute.

### macOS

With [Homebrew](https://brew.sh):

```bash
brew install eliorpom-cmd/tap/m3u8-sniffer
m3u8-sniffer-setup
```

Or download `m3u8-sniffer-<version>-macos.zip` from the [latest release](https://github.com/eliorpom-cmd/m3u8-sniffer/releases/latest),
unzip it where it will stay, and run `zsh install-host.sh` in Terminal from that folder. It installs Python,
yt-dlp and ffmpeg with Homebrew if they are missing.

### Windows

Download `m3u8-sniffer-<version>-windows.zip` from the [latest release](https://github.com/eliorpom-cmd/m3u8-sniffer/releases/latest),
unzip it where it will stay, and double-click **Installer (Windows).bat**. It installs Python and ffmpeg with
winget, and yt-dlp, if they are missing.

### Then, in Chrome

1. Open `chrome://extensions` and turn on **Developer mode** (top right).
2. Click **Load unpacked** and choose the `extension` folder (on macOS the setup copied its path: press ⌘⇧G and paste).
3. Pin the 🎬 icon.

Moving the folder afterwards breaks the extension (Chrome removes it at the next start): load it again from the
new place and run the setup again.

## Use

- Play the video and click 🎬. The popup lists the streams found in the tab, best quality first (measured from a
  segment when the playlist doesn't say), with duration, estimated size, audio tracks, subtitles and
  VF / VO / VOSTFR.
- **Copy** the link, or choose quality, audio and subtitles and click **Download**. The download runs in a
  terminal window (ctrl+C stops it).
- Files go to `~/Movies/Films` on macOS and `Videos\Films` on Windows (or `~/Documents/Films` if that folder
  exists): movies in `Films/`, episodes (S01E02, 1x02, "Saison 1 Épisode 2", E02) in
  `Séries/<Show (Year)>/Season NN/`, reusing the show's existing folder.
- Opening the popup also turns on a popup blocker for that tab: tabs it opens to other sites are closed.
- yt-dlp and ffmpeg are installed on first use if they are missing, and yt-dlp updates itself weekly on Windows.

## How it works

- `extension/background.js` records `.m3u8` requests per tab (including those made by a page's service worker,
  which some sites use to hide the real server) and analyses each stream through the native host.
- `host/m3u8_host.py` is a [native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
  host: `formats` (yt-dlp `-J`, plus ffprobe on one segment for streams without a declared resolution),
  `download` (starts yt-dlp in its own terminal window, since Chrome stops the host once it answers) and
  `series` (existing show folders). Only `http(s)` URLs are accepted, always after `--`, and the save path
  can't leave the videos folder. Only this extension's ID may talk to the host.
- `install-host.sh` (macOS) and `windows/install.ps1` register the host with Chrome.
- `m3u8-dl.sh` is a terminal-only version for macOS: paste a link, pick a quality.

## Tests

```bash
python3 -m unittest discover -s tests -t .   # native host: URL checks, paths, download command, playlists, framing
node --test tests/*.test.mjs                 # popup helpers: Jellyfin destination, VF/VO, file names
```

No network and no download: subprocess and HTTP calls are replaced. CI runs both on every push.

## Releases

`./make-release.sh` builds `dist/m3u8-sniffer-<version>-windows.zip` and `-macos.zip`. Pushing a `v*` tag runs the
tests and publishes both zips as a GitHub release.

## Known limits

- Chrome only (Edge and Brave register native hosts elsewhere).
- Requests a page's service worker serves from its own cache are invisible to the extension.
- DRM-protected streams (Widevine, FairPlay) can't be downloaded.

## License

[MIT](LICENSE)
