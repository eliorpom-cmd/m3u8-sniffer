#!/bin/zsh
# macOS setup: installs Python, yt-dlp and ffmpeg with Homebrew if missing,
# then registers the native host so the Chrome extension can launch downloads.
# Run it again if the folder moves.
set -e
# :a, not :A: run from Homebrew's opt/ link, the path must survive upgrades (no symlink resolving)
dir="${0:a:h}"
# The Homebrew formula names its own Python; otherwise Homebrew's python3
python="${M3U8_PYTHON:-}"

brew_bin=""
for b in /opt/homebrew/bin /usr/local/bin; do
  [[ -x "$b/brew" ]] && { brew_bin="$b"; break; }
done
if [[ -z "$brew_bin" ]]; then
  echo "Homebrew est nécessaire : installe-le depuis https://brew.sh puis relance ce script."
  exit 1
fi

missing=()
[[ -n "$python" || -x "$brew_bin/python3" ]] || missing+=(python)
[[ -x "$brew_bin/yt-dlp" ]] || missing+=(yt-dlp)
[[ -x "$brew_bin/ffprobe" ]] || missing+=(ffmpeg)
if (( ${#missing} )); then
  echo "Installation de ${missing[*]}…"
  "$brew_bin/brew" install "${missing[@]}"
fi

# Chrome runs the host with a minimal PATH: a wrapper names Homebrew's Python explicitly.
# The wrapper lives outside the project: Chrome fails to launch a script stored in ~/Documents
# ("Native host has exited") even with Documents access granted.
launcher_dir="$HOME/Library/Application Support/M3U8 Sniffer"
mkdir -p "$launcher_dir"
launcher="$launcher_dir/m3u8_host.sh"
cat > "$launcher" <<SH
#!/bin/sh
exec "${python:-$brew_bin/python3}" "$dir/host/m3u8_host.py" "\$@"
SH
chmod +x "$launcher" "$dir/host/m3u8_host.py"

dest="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
mkdir -p "$dest"
cat > "$dest/dev.byelior.m3u8.json" <<JSON
{
  "name": "dev.byelior.m3u8",
  "description": "M3U8 Sniffer downloader",
  "path": "$launcher",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://iklhldaffdlkmofoamlacnkcicnnigkf/"]
}
JSON

printf %s "$dir/extension" | pbcopy
echo "✅ Installé."
echo "Dans Chrome : chrome://extensions → Mode développeur → Charger l'extension non empaquetée,"
echo "puis ⌘⇧G et colle le chemin du dossier extension (déjà copié) : $dir/extension"
