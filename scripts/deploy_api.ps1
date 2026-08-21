<#
.SYNOPSIS
  都市別APIのLambdaコンテナイメージをECRにpushし、指定Lambdaを更新します。

.EXAMPLE
  # Existing Tokyo deployment
  .\scripts\deploy_api.ps1 -City tokyo

.EXAMPLE
  # Nagoya must name its own infrastructure explicitly
  .\scripts\deploy_api.ps1 `
    -City nagoya `
    -EcrRepository nagoyago-api `
    -LambdaFunction nagoyago-api `
    -ImageTag manual-test

.EXAMPLE
  # Sendai must also name its own infrastructure explicitly
  .\scripts\deploy_api.ps1 `
    -City sendai `
    -EcrRepository sendaigo-api `
    -LambdaFunction sendaigo-api `
    -ImageTag manual-test
#>

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateSet('tokyo', 'nagoya', 'sendai')]
    [string]$City = 'tokyo',

    [Parameter()]
    [string]$EcrRepository = '',

    [Parameter()]
    [string]$LambdaFunction = '',

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$Region = 'us-west-2',

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$ImageTag = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
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

if ([string]::IsNullOrWhiteSpace($EcrRepository)) {
    if ($City -eq 'tokyo') {
        $EcrRepository = 'toeigo-api'
    }
    else {
        throw "EcrRepository is required for city '$City'. Do not reuse the Tokyo default implicitly."
    }
}

if ([string]::IsNullOrWhiteSpace($LambdaFunction)) {
    if ($City -eq 'tokyo') {
        $LambdaFunction = 'toeigo-api'
    }
    else {
        throw "LambdaFunction is required for city '$City'. Do not reuse the Tokyo default implicitly."
    }
}

foreach ($commandName in @('aws', 'docker')) {
    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "Required command was not found: $commandName"
    }
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$apiDir = Join-Path $repoRoot 'api'
$dockerfile = Join-Path $apiDir 'Dockerfile'

if (-not (Test-Path -LiteralPath $dockerfile -PathType Leaf)) {
    throw "Dockerfile was not found: $dockerfile"
}

$accountId = (aws sts get-caller-identity --query Account --output text).Trim()
Assert-LastExitCode 'aws sts get-caller-identity'

if ($accountId -notmatch '^\d{12}$') {
    throw "Unexpected AWS account id: $accountId"
}

aws ecr describe-repositories `
    --region $Region `
    --repository-names $EcrRepository `
    --output json | Out-Null
Assert-LastExitCode 'aws ecr describe-repositories'

$functionConfigJson = aws lambda get-function-configuration `
    --region $Region `
    --function-name $LambdaFunction `
    --query '{PackageType:PackageType,Architecture:Architectures[0],AppCity:Environment.Variables.APP_CITY,NagoyaGtfsDir:Environment.Variables.NAGOYA_GTFS_DIR,NagoyaExpectedRevision:Environment.Variables.NAGOYA_GTFS_EXPECTED_REVISION,SendaiGtfsDir:Environment.Variables.SENDAI_GTFS_DIR,SendaiExpectedServiceDate:Environment.Variables.SENDAI_GTFS_EXPECTED_SERVICE_DATE}' `
    --output json
Assert-LastExitCode 'aws lambda get-function-configuration'

$functionConfig = $functionConfigJson | ConvertFrom-Json

if ($functionConfig.PackageType -ne 'Image') {
    throw "Lambda function '$LambdaFunction' is not an image-based function. PackageType=$($functionConfig.PackageType)"
}

$runtimeCity = if ($null -eq $functionConfig.AppCity) { '' } else { [string]$functionConfig.AppCity }
if ($City -eq 'tokyo') {
    if (-not [string]::IsNullOrEmpty($runtimeCity) -and $runtimeCity -ne 'tokyo') {
        throw "Lambda city mismatch. Requested=tokyo, APP_CITY=$runtimeCity"
    }
}
elseif ($runtimeCity -ne $City) {
    throw "Lambda city mismatch. Requested=$City, APP_CITY='$runtimeCity'. Configure the city-specific Lambda before deploying."
}

if ($City -eq 'nagoya') {
    if ([string]::IsNullOrWhiteSpace([string]$functionConfig.NagoyaGtfsDir)) {
        throw "Nagoya Lambda '$LambdaFunction' is missing NAGOYA_GTFS_DIR."
    }
    if ([string]::IsNullOrWhiteSpace([string]$functionConfig.NagoyaExpectedRevision)) {
        throw "Nagoya Lambda '$LambdaFunction' is missing NAGOYA_GTFS_EXPECTED_REVISION."
    }
}
elseif ($City -eq 'sendai') {
    if ([string]::IsNullOrWhiteSpace([string]$functionConfig.SendaiGtfsDir)) {
        throw "Sendai Lambda '$LambdaFunction' is missing SENDAI_GTFS_DIR."
    }
    if ([string]::IsNullOrWhiteSpace([string]$functionConfig.SendaiExpectedServiceDate)) {
        throw "Sendai Lambda '$LambdaFunction' is missing SENDAI_GTFS_EXPECTED_SERVICE_DATE."
    }
}

$dockerPlatform = switch ($functionConfig.Architecture) {
    'x86_64' { 'linux/amd64' }
    'arm64' { 'linux/arm64' }
    default {
        throw "Unsupported Lambda architecture: $($functionConfig.Architecture)"
    }
}

$registry = "$accountId.dkr.ecr.$Region.amazonaws.com"
$imageUri = "$registry/$EcrRepository`:$ImageTag"

Write-Host "AWS account : $accountId"
Write-Host "City        : $City"
Write-Host "Region      : $Region"
Write-Host "ECR repo    : $EcrRepository"
Write-Host "Lambda      : $LambdaFunction"
Write-Host "APP_CITY    : $runtimeCity"
Write-Host "Platform    : $dockerPlatform"
Write-Host "Image       : $imageUri"

$ecrPassword = aws ecr get-login-password --region $Region
Assert-LastExitCode 'aws ecr get-login-password'

$ecrPassword | docker login `
    --username AWS `
    --password-stdin $registry
Assert-LastExitCode 'docker login'

# Docker Desktop / BuildKit creates a provenance attestation by default. When that
# attestation is attached, the pushed tag can become an OCI image index even for a
# single --platform build. Lambda requires one concrete image manifest, not an
# image index / manifest list, so provenance is explicitly disabled here.
docker build `
    --platform $dockerPlatform `
    --provenance=false `
    --file $dockerfile `
    --tag $imageUri `
    $apiDir
Assert-LastExitCode 'docker build'

docker push $imageUri
Assert-LastExitCode 'docker push'

$imageManifestMediaType = (aws ecr batch-get-image `
    --region $Region `
    --repository-name $EcrRepository `
    --image-ids "imageTag=$ImageTag" `
    --query 'images[0].imageManifestMediaType' `
    --output text).Trim()
Assert-LastExitCode 'aws ecr batch-get-image'

$lambdaSupportedManifestMediaTypes = @(
    'application/vnd.docker.distribution.manifest.v2+json',
    'application/vnd.oci.image.manifest.v1+json'
)

if ($lambdaSupportedManifestMediaTypes -notcontains $imageManifestMediaType) {
    throw "ECR image manifest type is not supported by Lambda: $imageManifestMediaType. Expected a single Docker V2 or OCI image manifest."
}

Write-Host "Manifest    : $imageManifestMediaType"

aws lambda update-function-code `
    --region $Region `
    --function-name $LambdaFunction `
    --image-uri $imageUri `
    --output json | Out-Null
Assert-LastExitCode 'aws lambda update-function-code'

aws lambda wait function-updated `
    --region $Region `
    --function-name $LambdaFunction
Assert-LastExitCode 'aws lambda wait function-updated'

$deployedState = aws lambda get-function `
    --region $Region `
    --function-name $LambdaFunction `
    --query '{State:Configuration.State,LastUpdateStatus:Configuration.LastUpdateStatus,ImageUri:Code.ImageUri}' `
    --output json
Assert-LastExitCode 'aws lambda get-function'

Write-Host ''
Write-Host 'Deployment completed.'
Write-Host $deployedState
