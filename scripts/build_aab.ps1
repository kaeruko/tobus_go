<#
.SYNOPSIS
  都市別Google Play向けrelease AABを作成します。

.DESCRIPTION
  Tokyo / Nagoya / Sendai / Yokohama を同じコードベースから別applicationIdでビルドします。
  flavorとAPP_CITYは必ず同じ値を渡し、アプリ起動時にも不一致をfail-fastします。
  Android Maps API key は環境変数 GOOGLE_MAPS_ANDROID_API_KEY からのみ受け取り、
  release AABでは未設定を許可しません。

.EXAMPLE
  $env:GOOGLE_MAPS_ANDROID_API_KEY='AIza...'
  .\scripts\build_aab.ps1 -City tokyo

.EXAMPLE
  $env:GOOGLE_MAPS_ANDROID_API_KEY='AIza...'
  .\scripts\build_aab.ps1 `
    -City nagoya `
    -ApiBase 'https://nagoya-api.example.com'
#>

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateSet('tokyo', 'nagoya', 'sendai', 'yokohama')]
    [string]$City = 'tokyo',

    [Parameter()]
    [string]$ApiBase = ''
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

if ([string]::IsNullOrWhiteSpace($env:GOOGLE_MAPS_ANDROID_API_KEY)) {
    throw 'GOOGLE_MAPS_ANDROID_API_KEY is required. Create a restricted Android Maps key in your personal Google Cloud project and set it in this shell.'
}

if ([string]::IsNullOrWhiteSpace($ApiBase)) {
    if ($City -eq 'tokyo') {
        # Default to the migrated Tokyo production endpoint.
        $ApiBase = 'https://bzmpzqtr7kvczwgmyxlbrfkx6q0cldpy.lambda-url.us-west-2.on.aws'
    }
    else {
        throw "ApiBase is required for city '$City'. Do not fall back to the Tokyo API."
    }
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
$variantName = "${City}Release"
$aabName = "app-${City}-release.aab"
$aabPath = Join-Path $repoRoot "build\app\outputs\bundle\$variantName\$aabName"

if (-not (Test-Path -LiteralPath $pubspec -PathType Leaf)) {
    throw "pubspec.yaml was not found: $pubspec"
}

if (-not (Test-Path -LiteralPath $keyProperties -PathType Leaf)) {
    throw "Android release signing file was not found: $keyProperties"
}

Write-Host "Repository : $repoRoot"
Write-Host "City       : $City"
Write-Host "API base   : $ApiBase"
Write-Host "Maps key   : configured"
Write-Host "Output     : $aabPath"

Push-Location $repoRoot
try {
    flutter clean
    Assert-LastExitCode 'flutter clean'

    flutter pub get
    Assert-LastExitCode 'flutter pub get'

    flutter analyze --no-fatal-infos --no-fatal-warnings
    Assert-LastExitCode 'flutter analyze'

    flutter build appbundle `
        --release `
        --flavor $City `
        --dart-define="APP_CITY=$City" `
        --dart-define="API_BASE=$ApiBase"
    Assert-LastExitCode 'flutter build appbundle'

    if (-not (Test-Path -LiteralPath $aabPath -PathType Leaf)) {
        throw "AAB build reported success but output was not found: $aabPath"
    }

    $aab = Get-Item -LiteralPath $aabPath
    $sizeMb = [Math]::Round($aab.Length / 1MB, 2)

    Write-Host ''
    Write-Host 'AAB build completed.'
    Write-Host "City : $City"
    Write-Host "Path : $($aab.FullName)"
    Write-Host "Size : $sizeMb MB"
}
finally {
    Pop-Location
}
