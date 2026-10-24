# 毎日の実行スクリプト: 収集 → 新規リポジトリの解説を omp で作成 → サイトを作り直す。
# 月曜日は Star History の週間ランキングも取る（collect.py 側で判定）。
# 使い方: powershell -ExecutionPolicy Bypass -File run.ps1 [-Weekly]
param([switch]$Weekly)
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONIOENCODING = 'utf-8'

$root = $PSScriptRoot
$date = Get-Date -Format 'yyyy-MM-dd'
$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$log = Join-Path $logs "$date.log"
function Log($msg) { "[$(Get-Date -Format s)] $msg" | Out-File $log -Encoding utf8 -Append }
Set-Location $root

Log 'collect start'
$collectArgs = @('collect.py', '--date', $date)
if ($Weekly) { $collectArgs += '--weekly' }
& python @collectArgs 2>&1 | ForEach-Object { "$_" } | Out-File $log -Encoding utf8 -Append
if ($LASTEXITCODE -ne 0) { Log "collect failed ($LASTEXITCODE)"; exit 1 }

$pending = Get-Content (Join-Path $root 'data\pending.json') -Raw -Encoding utf8 | ConvertFrom-Json
if ($pending.repos.Count -gt 0) {
    Log "omp start: $($pending.repos.Count) repos"
    $omp = Join-Path $env:LOCALAPPDATA 'omp\omp.exe'
    & $omp -p --no-title --max-time 50m --cwd $root "@$(Join-Path $root 'prompt.md')" 2>&1 | ForEach-Object { "$_" } | Out-File $log -Encoding utf8 -Append
    Log "omp exit code $LASTEXITCODE"
} else {
    Log 'no new repos'
}

& python build.py 2>&1 | ForEach-Object { "$_" } | Out-File $log -Encoding utf8 -Append
if ($LASTEXITCODE -ne 0) { Log "build failed ($LASTEXITCODE)"; exit 1 }

# 生成物を GitHub に push して Pages を更新する（.github/workflows/pages.yml が site/ を公開する）。
Log 'publish start'
& git -C $root add -A 2>&1 | Out-File $log -Encoding utf8 -Append
& git -C $root diff --cached --quiet 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Log 'no changes to publish'
} else {
    & git -C $root commit -m "daily: $date" 2>&1 | Out-File $log -Encoding utf8 -Append
    Log "commit exit code $LASTEXITCODE"
    & git -C $root push origin main 2>&1 | Out-File $log -Encoding utf8 -Append
    Log "push exit code $LASTEXITCODE"
}

Log 'done'
exit 0
