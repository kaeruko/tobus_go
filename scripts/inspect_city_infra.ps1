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
    --query "{FunctionName:FunctionName,PackageType:PackageType,Architecture:Architectures[0],AppCity:Environment.Variables.APP_CITY,RouteSearchCore:Environment.Variables.ROUTE_SEARCH_CORE,HasGoogleMapsKey:contains(keys(Environment.Variables), 'GOOGLE_MAPS_API_KEY'),HasNagoyaGtfsDir:contains(keys(Environment.Variables), 'NAGOYA_GTFS_DIR'),HasNagoyaRevision:contains(keys(Environment.Variables), 'NAGOYA_GTFS_EXPECTED_REVISION'),HasNagoyaBundleBucket:contains(keys(Environment.Variables), 'NAGOYA_GTFS_BUNDLE_S3_BUCKET'),HasNagoyaBundleKey:contains(keys(Environment.Variables), 'NAGOYA_GTFS_BUNDLE_S3_KEY'),HasNagoyaBundleSha:contains(keys(Environment.Variables), 'NAGOYA_GTFS_BUNDLE_SHA256'),HasSendaiGtfsDir:contains(keys(Environment.Variables), 'SENDAI_GTFS_DIR'),HasSendaiServiceDate:contains(keys(Environment.Variables), 'SENDAI_GTFS_EXPECTED_SERVICE_DATE'),HasSendaiBundleBucket:contains(keys(Environment.Variables), 'SENDAI_GTFS_BUNDLE_S3_BUCKET'),HasSendaiBundleKey:contains(keys(Environment.Variables), 'SENDAI_GTFS_BUNDLE_S3_KEY'),HasSendaiBundleSha:contains(keys(Environment.Variables), 'SENDAI_GTFS_BUNDLE_SHA256')}" `
    --output json
Assert-LastExitCode 'aws lambda get-function-configuration'
$lambda = $lambdaJson | ConvertFrom-Json

if ($lambda.PackageType -ne 'Image') {
    throw "Lambda must use PackageType=Image. Actual=$($lambda.PackageType)"
}
if ($lambda.Architecture -ne 'x86_64') {
    throw "City Lambda must use x86_64. Actual=$($lambda.Architecture)"
}
if ([string]$lambda.AppCity -cne $City) {
    throw "Lambda APP_CITY mismatch. Expected=$City Actual='$($lambda.AppCity)'"
}
if (-not $lambda.HasGoogleMapsKey) {
    throw "Lambda is missing GOOGLE_MAPS_API_KEY: $LambdaFunction"
}

$routeSearchCore = if ([string]::IsNullOrWhiteSpace([string]$lambda.RouteSearchCore)) {
    'python'
}
else {
    [string]$lambda.RouteSearchCore
}
if (@('python', 'rust', 'shadow') -notcontains $routeSearchCore) {
    throw "Lambda ROUTE_SEARCH_CORE is invalid: '$routeSearchCore'"
}

if ($City -eq 'nagoya') {
    if (-not $lambda.HasNagoyaGtfsDir) {
        throw "Nagoya Lambda is missing NAGOYA_GTFS_DIR: $LambdaFunction"
    }
    if (-not $lambda.HasNagoyaRevision) {
        throw "Nagoya Lambda is missing NAGOYA_GTFS_EXPECTED_REVISION: $LambdaFunction"
    }
    if (-not $lambda.HasNagoyaBundleBucket) {
        throw "Nagoya Lambda is missing NAGOYA_GTFS_BUNDLE_S3_BUCKET: $LambdaFunction"
    }
    if (-not $lambda.HasNagoyaBundleKey) {
        throw "Nagoya Lambda is missing NAGOYA_GTFS_BUNDLE_S3_KEY: $LambdaFunction"
    }
    if (-not $lambda.HasNagoyaBundleSha) {
        throw "Nagoya Lambda is missing NAGOYA_GTFS_BUNDLE_SHA256: $LambdaFunction"
    }
}
elseif ($City -eq 'sendai') {
    if (-not $lambda.HasSendaiGtfsDir) {
        throw "Sendai Lambda is missing SENDAI_GTFS_DIR: $LambdaFunction"
    }
    if (-not $lambda.HasSendaiServiceDate) {
        throw "Sendai Lambda is missing SENDAI_GTFS_EXPECTED_SERVICE_DATE: $LambdaFunction"
    }
    if (-not $lambda.HasSendaiBundleBucket) {
        throw "Sendai Lambda is missing SENDAI_GTFS_BUNDLE_S3_BUCKET: $LambdaFunction"
    }
    if (-not $lambda.HasSendaiBundleKey) {
        throw "Sendai Lambda is missing SENDAI_GTFS_BUNDLE_S3_KEY: $LambdaFunction"
    }
    if (-not $lambda.HasSendaiBundleSha) {
        throw "Sendai Lambda is missing SENDAI_GTFS_BUNDLE_SHA256: $LambdaFunction"
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
Write-Host "Search core  : $routeSearchCore"
Write-Host "PackageType  : $($lambda.PackageType)"
Write-Host "Architecture : $($lambda.Architecture)"
Write-Host "Google key   : configured (value hidden)"
Write-Host 'GTFS bundle  : configured (bucket/key/SHA values hidden)'

$functionUrlOutput = @(
    & aws lambda get-function-url-config `
        --region $Region `
        --function-name $LambdaFunction `
        --query '{FunctionUrl:FunctionUrl,AuthType:AuthType,Cors:Cors}' `
        --output json 2>&1
)
$functionUrlExitCode = $LASTEXITCODE

if ($functionUrlExitCode -ne 0) {
    Write-Host 'Function URL : NOT CONFIRMED'
    Write-Host 'AWS CLI diagnostic:'
    $functionUrlOutput | ForEach-Object { Write-Host $_ }
    throw "aws lambda get-function-url-config failed with exit code $functionUrlExitCode."
}

$functionUrl = ($functionUrlOutput -join "`n") | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace([string]$functionUrl.FunctionUrl)) {
    throw "Lambda Function URL response did not contain FunctionUrl: $LambdaFunction"
}
if ([string]$functionUrl.AuthType -cne 'NONE') {
    throw "Lambda Function URL must use AuthType=NONE. Actual=$($functionUrl.AuthType)"
}
$allowMethods = @($functionUrl.Cors.AllowMethods)
foreach ($method in @('GET', 'POST')) {
    if ($allowMethods -notcontains $method) {
        throw "Lambda Function URL CORS is missing method: $method"
    }
}
if (@($functionUrl.Cors.AllowOrigins) -notcontains '*') {
    throw 'Lambda Function URL CORS must allow the configured public origin.'
}
foreach ($header in @('content-type', 'x-app-city')) {
    if (@($functionUrl.Cors.AllowHeaders) -notcontains $header) {
        throw "Lambda Function URL CORS is missing header: $header"
    }
}

$policyJson = aws lambda get-policy `
    --region $Region `
    --function-name $LambdaFunction `
    --query 'Policy' `
    --output text
Assert-LastExitCode 'aws lambda get-policy'
$policy = $policyJson | ConvertFrom-Json

$urlPermission = @($policy.Statement | Where-Object { $_.Sid -eq 'PublicFunctionUrlInvoke' })
if ($urlPermission.Count -ne 1 -or [string]$urlPermission[0].Action -cne 'lambda:InvokeFunctionUrl') {
    throw "Lambda policy is missing exact PublicFunctionUrlInvoke permission."
}
$urlAuthCondition = $urlPermission[0].Condition.StringEquals.PSObject.Properties['lambda:FunctionUrlAuthType']
if ($null -eq $urlAuthCondition -or [string]$urlAuthCondition.Value -cne 'NONE') {
    throw "PublicFunctionUrlInvoke must be restricted to FunctionUrlAuthType=NONE."
}

$invokePermission = @($policy.Statement | Where-Object { $_.Sid -eq 'PublicFunctionUrlInvokeFunction' })
if ($invokePermission.Count -ne 1 -or [string]$invokePermission[0].Action -cne 'lambda:InvokeFunction') {
    throw "Lambda policy is missing exact PublicFunctionUrlInvokeFunction permission."
}
$viaUrlCondition = $invokePermission[0].Condition.Bool.PSObject.Properties['lambda:InvokedViaFunctionUrl']
if ($null -eq $viaUrlCondition -or [string]$viaUrlCondition.Value -cne 'true') {
    throw "PublicFunctionUrlInvokeFunction must be restricted to InvokedViaFunctionUrl=true."
}

Write-Host "Function URL : $($functionUrl.FunctionUrl)"
Write-Host "URL auth     : $($functionUrl.AuthType)"
Write-Host 'URL policy   : InvokeFunctionUrl + InvokeFunction(via URL) confirmed'
Write-Host 'AWS city infrastructure preflight: READY'
