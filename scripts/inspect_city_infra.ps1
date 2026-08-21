<#
.SYNOPSIS
  Phase 8 production preflight for one city-specific AWS backend.

.DESCRIPTION
  Verifies the explicitly selected ECR repository and Lambda function without
  printing secret values. The command never falls back to Tokyo resources or
  to another region/name.

.EXAMPLE
  .\scripts\inspect_city_infra.ps1 -City nagoya

.EXAMPLE
  .\scripts\inspect_city_infra.ps1 -City sendai
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('nagoya', 'sendai')]
    [string]$City,

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$Region = 'us-west-2',

    [Parameter()]
    [string]$EcrRepository = '',

    [Parameter()]
    [string]$LambdaFunction = ''
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

$expectedResourceName = switch ($City) {
    'nagoya' { 'nagoyago-api' }
    'sendai' { 'sendaigo-api' }
    default { throw "Unsupported city: $City" }
}

if ([string]::IsNullOrWhiteSpace($EcrRepository)) {
    $EcrRepository = $expectedResourceName
}
if ([string]::IsNullOrWhiteSpace($LambdaFunction)) {
    $LambdaFunction = $expectedResourceName
}

$accountId = (aws sts get-caller-identity --query Account --output text).Trim()
Assert-LastExitCode 'aws sts get-caller-identity'
if ($accountId -notmatch '^\d{12}$') {
    throw "Unexpected AWS account id: $accountId"
}

$ecrJson = aws ecr describe-repositories `
    --region $Region `
    --repository-names $EcrRepository `
    --query 'repositories[0].{Name:repositoryName,Uri:repositoryUri}' `
    --output json
Assert-LastExitCode 'aws ecr describe-repositories'
$ecr = $ecrJson | ConvertFrom-Json
if ($null -eq $ecr -or [string]::IsNullOrWhiteSpace([string]$ecr.Name)) {
    throw "ECR repository was not returned: $EcrRepository"
}

$lambdaJson = aws lambda get-function-configuration `
    --region $Region `
    --function-name $LambdaFunction `
    --query "{FunctionName:FunctionName,PackageType:PackageType,Architecture:Architectures[0],AppCity:Environment.Variables.APP_CITY,HasGoogleMapsKey:contains(keys(Environment.Variables), 'GOOGLE_MAPS_API_KEY'),HasPlacesKey:contains(keys(Environment.Variables), 'PLACES_KEY'),HasNagoyaGtfsDir:contains(keys(Environment.Variables), 'NAGOYA_GTFS_DIR'),HasNagoyaRevision:contains(keys(Environment.Variables), 'NAGOYA_GTFS_EXPECTED_REVISION'),HasSendaiGtfsDir:contains(keys(Environment.Variables), 'SENDAI_GTFS_DIR'),HasSendaiServiceDate:contains(keys(Environment.Variables), 'SENDAI_GTFS_EXPECTED_SERVICE_DATE')}" `
    --output json
Assert-LastExitCode 'aws lambda get-function-configuration'
$lambda = $lambdaJson | ConvertFrom-Json

if ($lambda.PackageType -ne 'Image') {
    throw "Lambda must use PackageType=Image. Actual=$($lambda.PackageType)"
}
if ($lambda.Architecture -notin @('x86_64', 'arm64')) {
    throw "Unsupported Lambda architecture: $($lambda.Architecture)"
}
if ([string]$lambda.AppCity -cne $City) {
    throw "Lambda APP_CITY mismatch. Expected=$City Actual='$($lambda.AppCity)'"
}

if (-not $lambda.HasGoogleMapsKey -and -not $lambda.HasPlacesKey) {
    throw "Lambda is missing both GOOGLE_MAPS_API_KEY and PLACES_KEY: $LambdaFunction"
}

if ($City -eq 'nagoya') {
    if (-not $lambda.HasNagoyaGtfsDir) {
        throw "Nagoya Lambda is missing NAGOYA_GTFS_DIR: $LambdaFunction"
    }
    if (-not $lambda.HasNagoyaRevision) {
        throw "Nagoya Lambda is missing NAGOYA_GTFS_EXPECTED_REVISION: $LambdaFunction"
    }
}
elseif ($City -eq 'sendai') {
    if (-not $lambda.HasSendaiGtfsDir) {
        throw "Sendai Lambda is missing SENDAI_GTFS_DIR: $LambdaFunction"
    }
    if (-not $lambda.HasSendaiServiceDate) {
        throw "Sendai Lambda is missing SENDAI_GTFS_EXPECTED_SERVICE_DATE: $LambdaFunction"
    }
}

Write-Host 'AWS city infrastructure preflight: core resources OK'
Write-Host "Account      : $accountId"
Write-Host "Region       : $Region"
Write-Host "City         : $City"
Write-Host "ECR          : $($ecr.Name)"
Write-Host "ECR URI      : $($ecr.Uri)"
Write-Host "Lambda       : $($lambda.FunctionName)"
Write-Host "APP_CITY     : $($lambda.AppCity)"
Write-Host "PackageType  : $($lambda.PackageType)"
Write-Host "Architecture : $($lambda.Architecture)"
Write-Host "Google key   : configured (value hidden)"

# Function URL is inspected separately because a Lambda can validly exist before
# its public URL is created. A non-zero AWS response is surfaced verbatim and is
# not replaced by another API source.
$functionUrlOutput = @(
    & aws lambda get-function-url-config `
        --region $Region `
        --function-name $LambdaFunction `
        --query '{FunctionUrl:FunctionUrl,AuthType:AuthType}' `
        --output json 2>&1
)
$functionUrlExitCode = $LASTEXITCODE

if ($functionUrlExitCode -eq 0) {
    $functionUrl = ($functionUrlOutput -join "`n") | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace([string]$functionUrl.FunctionUrl)) {
        throw "Lambda Function URL response did not contain FunctionUrl: $LambdaFunction"
    }
    Write-Host "Function URL : $($functionUrl.FunctionUrl)"
    Write-Host "URL auth     : $($functionUrl.AuthType)"
}
else {
    Write-Host 'Function URL : NOT CONFIRMED'
    Write-Host 'AWS CLI diagnostic:'
    $functionUrlOutput | ForEach-Object { Write-Host $_ }
    throw "aws lambda get-function-url-config failed with exit code $functionUrlExitCode."
}

Write-Host 'AWS city infrastructure preflight: READY'
