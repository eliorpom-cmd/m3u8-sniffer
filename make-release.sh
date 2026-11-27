#!/bin/zsh
# Builds the three release zips in dist/: Windows, macOS and Linux (extension + host + installer).
# Never ships .keys/, .git or local notes. Used by the release workflow and by hand.
set -e
dir="${0:A:h}"
version=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1]))['version'])" "$dir/extension/manifest.json")
mkdir -p "$dir/dist"

for os in windows macos linux; do
  tmp=$(mktemp -d)
  out="$tmp/M3U8 Sniffer"
  mkdir -p "$out/host"
  cp -R "$dir/extension" "$out/"
  cp "$dir/host/m3u8_host.py" "$out/host/"
  cp "$dir/LICENSE" "$out/"
  if [[ $os == windows ]]; then
    mkdir -p "$out/windows"
    cp "$dir/windows/install.ps1" "$out/windows/"
    cp "$dir/Installer (Windows).bat" "$out/"
    # Notepad needs CRLF to show the lines
    sed 's/$/\r/' "$dir/windows/LISEZMOI.txt" > "$out/LISEZMOI.txt"
  elif [[ $os == linux ]]; then
    cp "$dir/install-host-linux.sh" "$out/"
    cp "$dir/linux/LISEZMOI.txt" "$out/"
    chmod +x "$out/install-host-linux.sh" "$out/host/m3u8_host.py"
  else
    cp "$dir/install-host.sh" "$out/"
    cp "$dir/macos/LISEZMOI.txt" "$out/"
  fi
  find "$tmp" -name .DS_Store -delete
  zip="$dir/dist/m3u8-sniffer-$version-$os.zip"
  # zip adds to an existing archive: start from a fresh file
  [[ -e "$zip" ]] && mv "$zip" "$tmp/previous.zip"
  (cd "$tmp" && zip -qr "$zip" "M3U8 Sniffer")
  echo "$zip"
done
