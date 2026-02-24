$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$db = Join-Path $root "data\edge\draftos.sqlite"

if (!(Test-Path $db)) {
  Write-Host "No DB found at $db, skipping backup."
  exit 0
}

$stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$dir = Join-Path $root "data\backups\$stamp"
New-Item -ItemType Directory -Force -Path $dir | Out-Null

Copy-Item $db (Join-Path $dir "draftos.sqlite") -Force
Write-Host "OK: Backup created at $dir"