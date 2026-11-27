#!/bin/bash
# Linux setup: checks Python 3 and ffmpeg, downloads yt-dlp next to the host, then registers
# the native host with Google Chrome and Chromium, for those that are installed.
# Never uses sudo: when something is missing it prints the command to run.
# Run it again if the folder moves. --non-interactive (CI): leaves the clipboard alone.
set -e
dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

interactive=1
for arg in "$@"; do
  case "$arg" in
    --non-interactive) interactive=0 ;;
    *) echo "Option inconnue : $arg (seule --non-interactive existe)"; exit 2 ;;
  esac
done

missing=()
command -v python3 >/dev/null || missing+=(python3)
{ command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; } || missing+=(ffmpeg)
if (( ${#missing[@]} )); then
  distro=""
  [[ -r /etc/os-release ]] && distro=$(. /etc/os-release && echo " ${ID:-} ${ID_LIKE:-} ")
  if [[ "$distro" == *" fedora "* ]]; then
    fix="sudo dnf install ffmpeg python3"
  else
    fix="sudo apt install ffmpeg python3"
  fi
  echo "Il manque ${missing[*]}. Installe-les avec :"
  echo "  $fix"
  echo "puis relance ce script."
  exit 1
fi

# The host downloads yt-dlp into host/bin and writes the manifests (one place for the paths it uses)
chmod +x "$dir/host/m3u8_host.py"
python3 "$dir/host/m3u8_host.py" --install

copied=""
if (( interactive )); then
  if command -v wl-copy >/dev/null && printf %s "$dir/extension" | wl-copy 2>/dev/null; then
    copied=" (déjà copié)"
  elif command -v xclip >/dev/null && printf %s "$dir/extension" | xclip -selection clipboard 2>/dev/null; then
    copied=" (déjà copié)"
  fi
fi
echo "✅ Installé."
echo "Dans Chrome : chrome://extensions → Mode développeur → Charger l'extension non empaquetée,"
echo "puis ctrl+L et colle le chemin du dossier extension$copied : $dir/extension"
