# Windows setup: Python, yt-dlp and ffmpeg, then registers the native host with Chrome.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$hostDir = Join-Path $root "host"

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}

function Find-Python {
  foreach ($cmd in @("py", "python")) {
    try {
      $pyArgs = if ($cmd -eq "py") { @("-3", "-c", "import sys; print(sys.executable)") } else { @("-c", "import sys; print(sys.executable)") }
      $exe = (& $cmd @pyArgs 2>$null | Select-Object -Last 1)
      # The Microsoft Store "python" alias prints nothing: skip it
      if ($exe -and (Test-Path $exe)) { return $exe.Trim() }
    } catch {}
  }
  # The silent per-user install doesn't touch PATH: look where it puts python.exe
  $found = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1
  if ($found) { return $found.FullName }
  return $null
}

# UTF-8 without BOM: Chrome reads the manifest as UTF-8, and a folder like C:\Users\Hélène must survive
function Write-Utf8($path, $text) {
  [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false))
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
  Write-Host "winget est introuvable. Installe « App Installer » depuis le Microsoft Store, puis relance." -ForegroundColor Red
  exit 1
}

Write-Host "1/4  Python…"
$python = Find-Python
if (-not $python) {
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-source-agreements --accept-package-agreements | Out-Null
  Refresh-Path
  $python = Find-Python
}
if (-not $python) { Write-Host "Python n'a pas pu être installé." -ForegroundColor Red; exit 1 }

Write-Host "2/4  ffmpeg…"
Refresh-Path
if (-not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
  winget install -e --id Gyan.FFmpeg --silent --accept-source-agreements --accept-package-agreements | Out-Null
}

Write-Host "3/4  yt-dlp…"
$bin = Join-Path $hostDir "bin"
New-Item -ItemType Directory -Force -Path $bin | Out-Null
$ytdlp = Join-Path $bin "yt-dlp.exe"
if (-not (Test-Path $ytdlp)) {
  [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
  Invoke-WebRequest "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe" -OutFile $ytdlp -UseBasicParsing
}

Write-Host "4/4  Liaison avec Chrome…"
# Chrome on Windows can't run a .py directly: a .bat starts it with the Python found above
$bat = Join-Path $hostDir "m3u8_host.bat"
# chcp 65001 makes cmd read the following lines as UTF-8 (accented paths); its output must not reach Chrome
Write-Utf8 $bat "@echo off`r`nchcp 65001 >nul`r`n`"$python`" `"%~dp0m3u8_host.py`" %*`r`n"
$manifest = Join-Path $hostDir "dev.byelior.m3u8.json"
@{
  name = "dev.byelior.m3u8"
  description = "M3U8 Sniffer downloader"
  path = $bat
  type = "stdio"
  allowed_origins = @("chrome-extension://iklhldaffdlkmofoamlacnkcicnnigkf/")
} | ConvertTo-Json | ForEach-Object { Write-Utf8 $manifest $_ }
reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\dev.byelior.m3u8" /ve /t REG_SZ /d "$manifest" /f | Out-Null

Write-Host ""
Write-Host "Installé." -ForegroundColor Green
Write-Host "Dans Chrome : chrome://extensions > Mode développeur > Charger l'extension non empaquetée > dossier « extension »."
Write-Host "Les vidéos arrivent dans $env:USERPROFILE\Videos\Films."
