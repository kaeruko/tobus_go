<#
.SYNOPSIS
  Select the Python, Rust, or shadow transit search core for one city Lambda.

.DESCRIPTION
  Preserves every existing Lambda environment variable and updates only
  ROUTE_SEARCH_CORE. APP_CITY is checked before the update, and RevisionId is
  supplied so a concurrent configuration change fails instead of being lost.

  Roll out in city order: sendai, yokohama, nagoya. Use Mode=python to roll back.

.EXAMPLE
  .\scripts\set_route_search_core.ps1 `
    -City sendai `
    -LambdaFunction sendaigo-api `
    -Mode shadow `
    -WhatIf

.EXAMPLE
  .\scripts\set_route_search_core.ps1 `
    -City sendai `
    -LambdaFunction sendaigo-api `
    -Mode python `
    -Confirm:$false
#>

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('sendai', 'yokohama', 'nagoya')]
    [string]$City,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$LambdaFunction,

    [Parameter(Mandatory = $true)]
    [ValidateSet('python', 'rust', 'shadow')]
    [string]$Mode,

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$Region = 'us-west-2'
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

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    throw 'Required command was not found: aws'
}

$configJson = aws lambda get-function-configuration `
    --region $Region `
    --function-name $LambdaFunction `
    --query '{RevisionId:RevisionId,AppCity:Environment.Variables.APP_CITY,Variables:Environment.Variables}' `
    --output json
Assert-LastExitCode 'aws lambda get-function-configuration'
$config = $configJson | ConvertFrom-Json

if ([string]$config.AppCity -cne $City) {
    throw "Lambda APP_CITY mismatch. Expected=$City Actual='$($config.AppCity)'"
}
if ([string]::IsNullOrWhiteSpace([string]$config.RevisionId)) {
    throw "Lambda did not return a RevisionId: $LambdaFunction"
}
if ($null -eq $config.Variables) {
    throw "Lambda has no environment variable map: $LambdaFunction"
}

$variables = [ordered]@{}
foreach ($property in $config.Variables.PSObject.Properties) {
    $variables[$property.Name] = [string]$property.Value
}
$previousMode = if ($variables.Contains('ROUTE_SEARCH_CORE')) {
    [string]$variables['ROUTE_SEARCH_CORE']
}
else {
    'python'
}
$variables['ROUTE_SEARCH_CORE'] = $Mode

Write-Host "City         : $City"
Write-Host "Region       : $Region"
Write-Host "Lambda       : $LambdaFunction"
Write-Host "Search core  : $previousMode -> $Mode"

if (-not $PSCmdlet.ShouldProcess(
        "$LambdaFunction in $Region",
        "set ROUTE_SEARCH_CORE from '$previousMode' to '$Mode'"
    )) {
    return
}

$tempRoot = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    ("tobus-route-search-core-" + [guid]::NewGuid().ToString('N'))
$environmentFile = Join-Path $tempRoot 'lambda-environment.json'

New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    $environmentPayload = @{ Variables = $variables } | ConvertTo-Json -Depth 6 -Compress
    [System.IO.File]::WriteAllText(
        $environmentFile,
        $environmentPayload,
        [System.Text.UTF8Encoding]::new($false)
    )

    aws lambda update-function-configuration `
        --region $Region `
        --function-name $LambdaFunction `
        --revision-id $config.RevisionId `
        --environment "file://$environmentFile" `
        --output json | Out-Null
    Assert-LastExitCode 'aws lambda update-function-configuration'

    aws lambda wait function-updated `
        --region $Region `
        --function-name $LambdaFunction
    Assert-LastExitCode 'aws lambda wait function-updated'

    $verifiedJson = aws lambda get-function-configuration `
        --region $Region `
        --function-name $LambdaFunction `
        --query '{AppCity:Environment.Variables.APP_CITY,RouteSearchCore:Environment.Variables.ROUTE_SEARCH_CORE}' `
        --output json
    Assert-LastExitCode 'aws lambda get-function-configuration verification'
    $verified = $verifiedJson | ConvertFrom-Json

    if ([string]$verified.AppCity -cne $City) {
        throw "Lambda APP_CITY changed during update. Expected=$City Actual='$($verified.AppCity)'"
    }
    if ([string]$verified.RouteSearchCore -cne $Mode) {
        throw "ROUTE_SEARCH_CORE verification failed. Expected=$Mode Actual='$($verified.RouteSearchCore)'"
    }

    Write-Host "ROUTE_SEARCH_CORE is now '$Mode'."
}
finally {
    if (Test-Path -LiteralPath $environmentFile -PathType Leaf) {
        Remove-Item -LiteralPath $environmentFile -Force
    }
    if (Test-Path -LiteralPath $tempRoot -PathType Container) {
        Remove-Item -LiteralPath $tempRoot -Force
    }
}
