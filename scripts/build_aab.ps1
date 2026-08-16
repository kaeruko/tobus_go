<#
.SYNOPSIS
  Google Play向けのrelease AABを作成します。

.DESCRIPTION
  flutter run の既定APIは 127.0.0.1 のまま維持し、AABビルド時だけ
  --dart-define=API_BASE=... で本番Lambda URLを注入します。

.EXAMPLE
  .\scripts\build_aab.ps1

.EXAMPLE
  .\scripts\build_aab.ps1 `
    -ApiBase 'https://example.lambda-url.us-west-2.on.aws'
#>

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$ApiBase = 'https://y6dmxuksrkf3nxp4encz5ez2ua0joxlp.lambda-url.us-west-2.on.aws'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-LastExitCode {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandName
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$CommandName failed with exit code $LASTEXITCODE."
    }
}

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
    throw 'Required command was not found: flutter'
}

$uri = $null
if (-not [System.Uri]::TryCreate($ApiBase, [System.UriKind]::Absolute, [ref]$uri)) {
    throw "ApiBase is not an absolute URL: $ApiBase"
}

if ($uri.Scheme -ne 'https') {
    throw "Store AAB requires an https API URL. ApiBase=$ApiBase"
}

if ($uri.Host -eq '127.0.0.1' -or $uri.Host -eq 'localhost') {
    throw "Store AAB must not use a local API host. ApiBase=$ApiBase"
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pubspec = Join-Path $repoRoot 'pubspec.yaml'
$keyProperties = Join-Path $repoRoot 'android\key.properties'
$aabPath = Join-Path $repoRoot 'build\app\outputs\bundle\release\app-release.aab'

if (-not (Test-Path -LiteralPath $pubspec -PathType Leaf)) {
    throw "pubspec.yaml was not found: $pubspec"
}

if (-not (Test-Path -LiteralPath $keyProperties -PathType Leaf)) {
    throw "Android release signing file was not found: $keyProperties"
}

Write-Host "Repository : $repoRoot"
Write-Host "API base   : $ApiBase"
Write-Host "Output     : $aabPath"

Push-Location $repoRoot
try {
    flutter clean
    Assert-LastExitCode 'flutter clean'

    flutter pub get
    Assert-LastExitCode 'flutter pub get'

    flutter analyze
    Assert-LastExitCode 'flutter analyze'

    flutter build appbundle `
        --release `
        --dart-define="API_BASE=$ApiBase"
    Assert-LastExitCode 'flutter build appbundle'

    if (-not (Test-Path -LiteralPath $aabPath -PathType Leaf)) {
        throw "AAB build reported success but output was not found: $aabPath"
    }

    $aab = Get-Item -LiteralPath $aabPath
    $sizeMb = [Math]::Round($aab.Length / 1MB, 2)

    Write-Host ''
    Write-Host 'AAB build completed.'
    Write-Host "Path : $($aab.FullName)"
    Write-Host "Size : $sizeMb MB"
}
finally {
    Pop-Location
}
