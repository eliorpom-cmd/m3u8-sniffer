#!/bin/zsh
# Download an m3u8 (HLS) stream: paste the link, pick a quality, get an .mp4 in ~/Documents/Films/Films (Jellyfin movie library).

read "url?Lien m3u8 : "
url="${url//\'/}"; url="${url// /}"
[[ -z "$url" ]] && { echo "Aucun lien."; exit 1; }

echo "\nAnalyse du flux…"
# One line per video format: id|height|kbps, best first
formats=("${(@f)$(yt-dlp -J --no-warnings "$url" </dev/null 2>/dev/null | python3 -c '
import json, sys
d = json.load(sys.stdin)
fs = [f for f in d.get("formats", []) if f.get("vcodec") != "none"]
fs.sort(key=lambda f: (f.get("height") or 0, f.get("tbr") or 0), reverse=True)
for f in fs:
    print("%s|%s|%d" % (f["format_id"], f.get("height") or "?", f.get("tbr") or 0))
')}")

if [[ -z "${formats[1]}" ]]; then
  echo "Qualités illisibles, téléchargement en meilleure qualité."
  fmt="bv*+ba/b"
else
  echo "Qualités disponibles :"
  for i in {1..${#formats}}; do
    parts=("${(@s:|:)formats[$i]}")
    echo "  $i) ${parts[2]}p  (${parts[3]} kbps)"
  done
  read "choice?Choix [1 = meilleure] : "
  id="${${(@s:|:)formats[${choice:-1}]}[1]}"
  fmt="${id}+bestaudio/${id}"
fi

read "name?Nom du fichier (vide = auto) : "
out="$HOME/Documents/Films/Films/${name:-%(title)s}.%(ext)s"

yt-dlp -f "$fmt" --merge-output-format mp4 -N 8 -o "$out" "$url" </dev/null \
  && echo "\n✅ Terminé → ~/Documents/Films/Films" && open "$HOME/Documents/Films/Films"
