#!/bin/zsh
# macOS setup: installs Python, yt-dlp and ffmpeg with Homebrew if missing,
# then registers the native host so the Chrome extension can launch downloads.
# Run it again if the folder moves.
set -e
dir="${0:A:h}"

brew_bin=""
for b in /opt/homebrew/bin /usr/local/bin; do
  [[ -x "$b/brew" ]] && { brew_bin="$b"; break; }
done
if [[ -z "$brew_bin" ]]; then
  echo "Homebrew est nécessaire : installe-le depuis https://brew.sh puis relance ce script."
  exit 1
fi

missing=()
[[ -x "$brew_bin/python3" ]] || missing+=(python)
[[ -x "$brew_bin/yt-dlp" ]] || missing+=(yt-dlp)
[[ -x "$brew_bin/ffprobe" ]] || missing+=(ffmpeg)
if (( ${#missing} )); then
  echo "Installation de ${missing[*]}…"
  "$brew_bin/brew" install "${missing[@]}"
fi

# Chrome runs the host with a minimal PATH: a wrapper names Homebrew's Python explicitly
cat > "$dir/host/m3u8_host.sh" <<SH
#!/bin/sh
exec "$brew_bin/python3" "$dir/host/m3u8_host.py" "\$@"
SH
chmod +x "$dir/host/m3u8_host.sh" "$dir/host/m3u8_host.py"

dest="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
mkdir -p "$dest"
cat > "$dest/dev.byelior.m3u8.json" <<JSON
{
  "name": "dev.byelior.m3u8",
  "description": "M3U8 Sniffer downloader",
  "path": "$dir/host/m3u8_host.sh",
  "type": "stdio",
  "allowed_origins": ["chrome-extension://iklhldaffdlkmofoamlacnkcicnnigkf/"]
}
JSON

printf %s "$dir/extension" | pbcopy
echo "✅ Installé."
echo "Dans Chrome : chrome://extensions → Mode développeur → Charger l'extension non empaquetée,"
echo "puis ⌘⇧G et colle le chemin du dossier extension (déjà copié) : $dir/extension"
