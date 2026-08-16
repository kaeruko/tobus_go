<#
.SYNOPSIS
  api/ の Lambda コンテナイメージを ECR に push し、Lambda を更新します。

.EXAMPLE
  .\scripts\deploy_api.ps1

.EXAMPLE
  .\scripts\deploy_api.ps1 `
    -ImageTag manual-test

.EXAMPLE
  .\scripts\deploy_api.ps1 `
    -Region us-west-2 `
    -EcrRepository toeigo-api `
    -LambdaFunction toeigo-api `
    -ImageTag manual-test
#>

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$EcrRepository = 'toeigo-api',

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$LambdaFunction = 'toeigo-api',

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
    --query '{PackageType:PackageType,Architecture:Architectures[0]}' `
    --output json
Assert-LastExitCode 'aws lambda get-function-configuration'

$functionConfig = $functionConfigJson | ConvertFrom-Json

if ($functionConfig.PackageType -ne 'Image') {
    throw "Lambda function '$LambdaFunction' is not an image-based function. PackageType=$($functionConfig.PackageType)"
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
Write-Host "Region      : $Region"
Write-Host "ECR repo    : $EcrRepository"
Write-Host "Lambda      : $LambdaFunction"
Write-Host "Platform    : $dockerPlatform"
Write-Host "Image       : $imageUri"

$ecrPassword = aws ecr get-login-password --region $Region
Assert-LastExitCode 'aws ecr get-login-password'

$ecrPassword | docker login `
    --username AWS `
    --password-stdin $registry
Assert-LastExitCode 'docker login'

docker build `
    --platform $dockerPlatform `
    --file $dockerfile `
    --tag $imageUri `
    $apiDir
Assert-LastExitCode 'docker build'

docker push $imageUri
Assert-LastExitCode 'docker push'

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
