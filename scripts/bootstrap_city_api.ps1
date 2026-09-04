<#
.SYNOPSIS
  Create the first production AWS backend for Nagoya or Sendai.

.DESCRIPTION
  This is a one-time bootstrap for a city that does not already have its own
  production ECR/Lambda backend. It deliberately does not reuse Tokyo resources.

  The script:
  - validates one already-approved local GTFS directory and its city manifest;
  - requires GOOGLE_MAPS_API_KEY from the current process environment without printing it;
  - creates the city base stack (private/versioned S3, immutable ECR, Lambda role,
    retained log group);
  - packages the validated GTFS directory, uploads that exact bundle to the city
    S3 prefix, and records the bundle SHA-256 in Lambda environment variables;
  - builds one x86_64 Lambda image and pushes it under an immutable unique tag;
  - creates the city Lambda only if it does not already exist;
  - creates a public Function URL and both permissions required by AWS for new
    Function URLs (InvokeFunctionUrl and InvokeFunction via Function URL);
  - runs inspect_city_infra.ps1 at the end.

  Secret values are written only to a temporary UTF-8 JSON file used by the AWS
  CLI and are removed in finally. Secret values are never printed or placed in
  command arguments directly. The script does not read a local .env file and does
  not search another Lambda or secret source when GOOGLE_MAPS_API_KEY is missing.

.EXAMPLE
  .\scripts\bootstrap_city_api.ps1 `
    -City nagoya `
    -GtfsDir C:\data\nagoya\2026-03-28 `
    -ExpectedDataVersion 2026-03-28

.EXAMPLE
  .\scripts\bootstrap_city_api.ps1 `
    -City sendai `
    -GtfsDir C:\data\sendai\2026-08-22 `
    -ExpectedDataVersion 2026-08-22
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('nagoya', 'sendai')]
    [string]$City,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$GtfsDir,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$ExpectedDataVersion,

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$Region = 'us-west-2',

    [Parameter()]
    [ValidateRange(128, 10240)]
    [int]$MemorySizeMb = 2048,

    [Parameter()]
    [ValidateRange(1, 900)]
    [int]$TimeoutSeconds = 60,

    [Parameter()]
    [ValidateRange(512, 10240)]
    [int]$EphemeralStorageMb = 1024,

    [Parameter()]
    [ValidateSet('python', 'rust', 'shadow')]
    [string]$RouteSearchCore = 'python',

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

function Get-StackOutputValue {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Outputs,
        [Parameter(Mandatory = $true)]
        [string]$Key
    )
    $matches = @($Outputs | Where-Object { [string]$_.OutputKey -eq $Key })
    if ($matches.Count -ne 1) {
        throw "Expected exactly one CloudFormation output '$Key', found $($matches.Count)."
    }
    $value = [string]$matches[0].OutputValue
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "CloudFormation output '$Key' is empty."
    }
    return $value
}

function Get-GoogleMapsKeyFromEnvironment {
    $value = [Environment]::GetEnvironmentVariable('GOOGLE_MAPS_API_KEY', 'Process')
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw 'GOOGLE_MAPS_API_KEY process environment variable is required.'
    }
    if (
        ($value.StartsWith('"') -and $value.EndsWith('"')) -or
        ($value.StartsWith("'") -and $value.EndsWith("'"))
    ) {
        throw 'GOOGLE_MAPS_API_KEY process environment variable must be unquoted.'
    }
    return $value
}

function Assert-LambdaDoesNotExist {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FunctionName,
        [Parameter(Mandatory = $true)]
        [string]$AwsRegion
    )
    $output = @(
        & aws lambda get-function `
            --region $AwsRegion `
            --function-name $FunctionName `
            --output json 2>&1
    )
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 0) {
        throw "Lambda '$FunctionName' already exists. bootstrap_city_api.ps1 never mutates an existing city Lambda; use deploy_api.ps1 after inspecting it."
    }
    $text = $output -join "`n"
    if ($text -notmatch 'ResourceNotFoundException') {
        Write-Host 'AWS CLI diagnostic:'
        $output | ForEach-Object { Write-Host $_ }
        throw "Could not prove Lambda '$FunctionName' is absent."
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
$baseTemplate = Join-Path $repoRoot 'infra\city-api-base.yaml'
$inspectScript = Join-Path $PSScriptRoot 'inspect_city_infra.ps1'

foreach ($requiredFile in @($dockerfile, $baseTemplate, $inspectScript)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) {
        throw "Required repository file was not found: $requiredFile"
    }
}

$resolvedGtfsDir = (Resolve-Path -LiteralPath $GtfsDir).Path
if (-not (Test-Path -LiteralPath $resolvedGtfsDir -PathType Container)) {
    throw "GTFS directory was not found: $resolvedGtfsDir"
}

$manifestFileName = switch ($City) {
    'nagoya' { 'nagoya_gtfs_manifest.json' }
    'sendai' { 'sendai_gtfs_manifest.json' }
    default { throw "Unsupported city: $City" }
}
$manifestPath = Join-Path $resolvedGtfsDir $manifestFileName
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Validated GTFS directory is missing ${manifestFileName}: $resolvedGtfsDir"
}

foreach ($requiredGtfsFile in @('stops.txt', 'routes.txt', 'trips.txt', 'stop_times.txt')) {
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedGtfsDir $requiredGtfsFile) -PathType Leaf)) {
        throw "Validated GTFS directory is missing ${requiredGtfsFile}: $resolvedGtfsDir"
    }
}
if (
    -not (Test-Path -LiteralPath (Join-Path $resolvedGtfsDir 'calendar.txt') -PathType Leaf) -and
    -not (Test-Path -LiteralPath (Join-Path $resolvedGtfsDir 'calendar_dates.txt') -PathType Leaf)
) {
    throw "Validated GTFS directory requires calendar.txt or calendar_dates.txt: $resolvedGtfsDir"
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($City -eq 'nagoya') {
    $installedVersion = [string]$manifest.revision
    if ($installedVersion -cne $ExpectedDataVersion) {
        throw "Nagoya manifest revision mismatch. Expected=$ExpectedDataVersion Installed='$installedVersion'"
    }
}
else {
    $installedVersion = [string]$manifest.validated_service_date
    if ($installedVersion -cne $ExpectedDataVersion) {
        throw "Sendai manifest service-date mismatch. Expected=$ExpectedDataVersion Installed='$installedVersion'"
    }
    $validFrom = [string]$manifest.valid_from
    $validUntil = [string]$manifest.valid_until
    if ([string]::IsNullOrWhiteSpace($validFrom) -or [string]::IsNullOrWhiteSpace($validUntil)) {
        throw 'Sendai manifest is missing valid_from or valid_until.'
    }
    if ($ExpectedDataVersion -lt $validFrom -or $ExpectedDataVersion -gt $validUntil) {
        throw "Sendai expected service date is outside manifest coverage. Date=$ExpectedDataVersion Coverage=$validFrom..$validUntil"
    }
}

$googleMapsKey = Get-GoogleMapsKeyFromEnvironment
Write-Host 'Local production inputs: validated (Google key value hidden)'

$accountId = (aws sts get-caller-identity --query Account --output text).Trim()
Assert-LastExitCode 'aws sts get-caller-identity'
if ($accountId -notmatch '^\d{12}$') {
    throw "Unexpected AWS account id: $accountId"
}

$resourceName = "${City}go-api"
$stackName = "tobus-go-${City}-api-base"
Assert-LambdaDoesNotExist -FunctionName $resourceName -AwsRegion $Region

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) (
    'tobus-go-' + $City + '-bootstrap-' + [guid]::NewGuid().ToString('N')
)
New-Item -ItemType Directory -Path $tempRoot | Out-Null
$bundlePath = Join-Path $tempRoot 'gtfs-bundle.zip'
$environmentFile = Join-Path $tempRoot 'lambda-environment.json'
$corsFile = Join-Path $tempRoot 'function-url-cors.json'

try {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $resolvedGtfsDir,
        $bundlePath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )
    if (-not (Test-Path -LiteralPath $bundlePath -PathType Leaf)) {
        throw 'GTFS bundle ZIP was not created.'
    }
    $bundleSha256 = (Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($bundleSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "Unexpected GTFS bundle SHA-256: $bundleSha256"
    }
    $bundleKey = "gtfs/$City/$ExpectedDataVersion/$bundleSha256.zip"

    Write-Host "AWS account : $accountId"
    Write-Host "Region      : $Region"
    Write-Host "City        : $City"
    Write-Host "Base stack  : $stackName"
    Write-Host "ECR/Lambda  : $resourceName"
    Write-Host "GTFS version: $ExpectedDataVersion"
    Write-Host "Bundle SHA  : $bundleSha256"

    aws cloudformation deploy `
        --region $Region `
        --stack-name $stackName `
        --template-file $baseTemplate `
        --parameter-overrides "City=$City" `
        --capabilities CAPABILITY_IAM `
        --no-fail-on-empty-changeset
    Assert-LastExitCode 'aws cloudformation deploy city-api-base'

    $outputsJson = aws cloudformation describe-stacks `
        --region $Region `
        --stack-name $stackName `
        --query 'Stacks[0].Outputs' `
        --output json
    Assert-LastExitCode 'aws cloudformation describe-stacks'
    $outputs = @($outputsJson | ConvertFrom-Json)

    $ecrRepository = Get-StackOutputValue -Outputs $outputs -Key 'EcrRepositoryName'
    $ecrUri = Get-StackOutputValue -Outputs $outputs -Key 'EcrRepositoryUri'
    $gtfsBucket = Get-StackOutputValue -Outputs $outputs -Key 'GtfsBucketName'
    $roleArn = Get-StackOutputValue -Outputs $outputs -Key 'ApiExecutionRoleArn'
    $functionName = Get-StackOutputValue -Outputs $outputs -Key 'LambdaFunctionName'

    if ($ecrRepository -cne $resourceName) {
        throw "CloudFormation ECR name mismatch. Expected=$resourceName Actual=$ecrRepository"
    }
    if ($functionName -cne $resourceName) {
        throw "CloudFormation Lambda name mismatch. Expected=$resourceName Actual=$functionName"
    }

    $headOutput = @(
        & aws s3api head-object `
            --region $Region `
            --bucket $gtfsBucket `
            --key $bundleKey `
            --output json 2>&1
    )
    $headExitCode = $LASTEXITCODE
    if ($headExitCode -eq 0) {
        throw "GTFS bundle already exists in S3; refusing overwrite: s3://$gtfsBucket/$bundleKey"
    }
    $headText = $headOutput -join "`n"
    if ($headText -notmatch '(404|Not Found|NoSuchKey)') {
        Write-Host 'AWS CLI diagnostic:'
        $headOutput | ForEach-Object { Write-Host $_ }
        throw 'Could not prove the target GTFS bundle key is absent.'
    }

    aws s3 cp `
        $bundlePath `
        "s3://$gtfsBucket/$bundleKey" `
        --region $Region `
        --only-show-errors
    Assert-LastExitCode 'aws s3 cp GTFS bundle'

    $uploadedLength = (aws s3api head-object `
        --region $Region `
        --bucket $gtfsBucket `
        --key $bundleKey `
        --query 'ContentLength' `
        --output text).Trim()
    Assert-LastExitCode 'aws s3api head-object uploaded GTFS bundle'
    $localLength = (Get-Item -LiteralPath $bundlePath).Length
    if ([int64]$uploadedLength -ne [int64]$localLength) {
        throw "Uploaded GTFS bundle size mismatch. Local=$localLength S3=$uploadedLength"
    }

    $registry = "$accountId.dkr.ecr.$Region.amazonaws.com"
    $imageUri = "$ecrUri`:$ImageTag"
    $ecrPassword = aws ecr get-login-password --region $Region
    Assert-LastExitCode 'aws ecr get-login-password'
    $ecrPassword | docker login `
        --username AWS `
        --password-stdin $registry
    Assert-LastExitCode 'docker login'

    docker build `
        --platform linux/amd64 `
        --provenance=false `
        --file $dockerfile `
        --tag $imageUri `
        $apiDir
    Assert-LastExitCode 'docker build city API'

    docker push $imageUri
    Assert-LastExitCode 'docker push city API'

    $manifestMediaType = (aws ecr batch-get-image `
        --region $Region `
        --repository-name $ecrRepository `
        --image-ids "imageTag=$ImageTag" `
        --query 'images[0].imageManifestMediaType' `
        --output text).Trim()
    Assert-LastExitCode 'aws ecr batch-get-image'
    $supportedMediaTypes = @(
        'application/vnd.docker.distribution.manifest.v2+json',
        'application/vnd.oci.image.manifest.v1+json'
    )
    if ($supportedMediaTypes -notcontains $manifestMediaType) {
        throw "ECR image manifest type is not supported by Lambda: $manifestMediaType"
    }

    $variables = @{
        APP_CITY = $City
        GOOGLE_MAPS_API_KEY = $googleMapsKey
        ROUTE_SEARCH_CORE = $RouteSearchCore
    }
    if ($City -eq 'nagoya') {
        $variables['NAGOYA_GTFS_DIR'] = '/tmp/gtfs/nagoya'
        $variables['NAGOYA_GTFS_EXPECTED_REVISION'] = $ExpectedDataVersion
        $variables['NAGOYA_GTFS_BUNDLE_S3_BUCKET'] = $gtfsBucket
        $variables['NAGOYA_GTFS_BUNDLE_S3_KEY'] = $bundleKey
        $variables['NAGOYA_GTFS_BUNDLE_SHA256'] = $bundleSha256
    }
    else {
        $variables['SENDAI_GTFS_DIR'] = '/tmp/gtfs/sendai'
        $variables['SENDAI_GTFS_EXPECTED_SERVICE_DATE'] = $ExpectedDataVersion
        $variables['SENDAI_GTFS_BUNDLE_S3_BUCKET'] = $gtfsBucket
        $variables['SENDAI_GTFS_BUNDLE_S3_KEY'] = $bundleKey
        $variables['SENDAI_GTFS_BUNDLE_SHA256'] = $bundleSha256
    }

    $environmentPayload = @{ Variables = $variables } | ConvertTo-Json -Depth 6 -Compress
    [System.IO.File]::WriteAllText(
        $environmentFile,
        $environmentPayload,
        [System.Text.UTF8Encoding]::new($false)
    )

    $corsPayload = @{
        AllowOrigins = @('*')
        AllowHeaders = @('content-type', 'x-app-city')
        # Lambda Function URL answers the preflight request. AllowMethods lists
        # the actual browser methods and AWS rejects the 7-character OPTIONS.
        AllowMethods = @('GET', 'POST')
        MaxAge = 3600
    } | ConvertTo-Json -Depth 5 -Compress
    [System.IO.File]::WriteAllText(
        $corsFile,
        $corsPayload,
        [System.Text.UTF8Encoding]::new($false)
    )

    $created = $false
    for ($attempt = 1; $attempt -le 4; $attempt++) {
        $createOutput = @(
            & aws lambda create-function `
                --region $Region `
                --function-name $functionName `
                --package-type Image `
                --code "ImageUri=$imageUri" `
                --role $roleArn `
                --architectures x86_64 `
                --timeout $TimeoutSeconds `
                --memory-size $MemorySizeMb `
                --ephemeral-storage "Size=$EphemeralStorageMb" `
                --environment "file://$environmentFile" `
                --query '{FunctionName:FunctionName,State:State,PackageType:PackageType}' `
                --output json 2>&1
        )
        $createExitCode = $LASTEXITCODE
        if ($createExitCode -eq 0) {
            $created = $true
            break
        }
        $createText = $createOutput -join "`n"
        if (
            $attempt -lt 4 -and
            $createText -match 'role defined for the function cannot be assumed by Lambda'
        ) {
            Write-Host "Lambda role propagation not ready; retrying exact create-function ($attempt/4)..."
            Start-Sleep -Seconds 5
            continue
        }
        $safeCreateText = $createText -replace [regex]::Escape($googleMapsKey), '<redacted>'
        throw "aws lambda create-function failed with exit code $createExitCode.`n$safeCreateText"
    }
    if (-not $created) {
        throw 'Lambda create-function did not complete.'
    }

    aws lambda wait function-active `
        --region $Region `
        --function-name $functionName
    Assert-LastExitCode 'aws lambda wait function-active'

    aws lambda create-function-url-config `
        --region $Region `
        --function-name $functionName `
        --auth-type NONE `
        --cors "file://$corsFile" `
        --output json | Out-Null
    Assert-LastExitCode 'aws lambda create-function-url-config'

    aws lambda add-permission `
        --region $Region `
        --function-name $functionName `
        --statement-id PublicFunctionUrlInvoke `
        --action lambda:InvokeFunctionUrl `
        --principal '*' `
        --function-url-auth-type NONE `
        --output json | Out-Null
    Assert-LastExitCode 'aws lambda add-permission InvokeFunctionUrl'

    aws lambda add-permission `
        --region $Region `
        --function-name $functionName `
        --statement-id PublicFunctionUrlInvokeFunction `
        --action lambda:InvokeFunction `
        --principal '*' `
        --invoked-via-function-url `
        --output json | Out-Null
    Assert-LastExitCode 'aws lambda add-permission InvokeFunction via Function URL'

    & $inspectScript -City $City -Region $Region
    if ($LASTEXITCODE -ne 0) {
        throw "inspect_city_infra.ps1 failed with exit code $LASTEXITCODE."
    }

    $functionUrl = (aws lambda get-function-url-config `
        --region $Region `
        --function-name $functionName `
        --query 'FunctionUrl' `
        --output text).Trim()
    Assert-LastExitCode 'aws lambda get-function-url-config'

    Write-Host ''
    Write-Host 'City API bootstrap completed.'
    Write-Host "City         : $City"
    Write-Host "Region       : $Region"
    Write-Host "ECR          : $ecrRepository"
    Write-Host "Lambda       : $functionName"
    Write-Host "Function URL : $functionUrl"
    Write-Host "GTFS S3 key  : $bundleKey"
    Write-Host "GTFS SHA-256 : $bundleSha256"
    Write-Host 'Google key   : configured (value hidden)'
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
