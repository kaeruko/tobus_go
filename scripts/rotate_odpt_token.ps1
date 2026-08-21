<#
.SYNOPSIS
  Rotate the ODPT API token used by the existing Tokyo AWS runtime without
  replacing unrelated Lambda environment variables.

.DESCRIPTION
  - Requires ODPT_API_TOKEN in the current PowerShell environment.
  - Validates the token against the authenticated ODPT API before touching AWS.
  - Updates ODPT_API_TOKEN on the Tokyo API Lambda while preserving every other
    environment variable exactly.
  - If the legacy ODPT_API_KEY alias already exists, updates that existing alias
    to the same credential; it never creates the legacy alias.
  - Uses the Lambda RevisionId so a concurrent configuration change aborts
    instead of being overwritten.
  - Updates the CloudFormation-managed toeigo-gtfs-refresh stack parameter so
    the refresh Lambda is not left in CloudFormation drift.
  - Verifies both Lambda functions contain the requested token after updates.
  - Never prints the token.
#>

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$Region = 'us-west-2',

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$ApiFunction = 'toeigo-api',

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$RefreshStack = 'toeigo-gtfs-refresh'
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

function Convert-PropertiesToHashtable {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Object
    )
    $result = @{}
    foreach ($property in $Object.PSObject.Properties) {
        $result[$property.Name] = [string]$property.Value
    }
    return $result
}

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    throw 'Required command was not found: aws'
}

$token = $env:ODPT_API_TOKEN
if ([string]::IsNullOrWhiteSpace($token)) {
    throw 'ODPT_API_TOKEN is required in the current environment.'
}

# Validate the exact token first. Any HTTP exception is intentionally replaced
# with a sanitized error so a URL containing the token is never printed.
$validationUri = 'https://api.odpt.org/api/v4/odpt:BusstopPole'
try {
    $validationResponse = Invoke-WebRequest `
        -Uri $validationUri `
        -Method Get `
        -Body @{
            'odpt:operator' = 'odpt.Operator:Toei'
            'acl:consumerKey' = $token
        } `
        -TimeoutSec 20 `
        -ErrorAction Stop
}
catch {
    throw 'ODPT token validation request failed. AWS was not modified.'
}
if ($validationResponse.StatusCode -ne 200) {
    throw "ODPT token validation failed with HTTP $($validationResponse.StatusCode). AWS was not modified."
}
Write-Host 'ODPT token validation: OK'

# Fetch the current API Lambda environment and RevisionId in one snapshot. The
# RevisionId makes the following write optimistic-locking safe.
$apiConfigJson = aws lambda get-function-configuration `
    --region $Region `
    --function-name $ApiFunction `
    --query '{RevisionId:RevisionId,Variables:Environment.Variables}' `
    --output json
Assert-LastExitCode 'aws lambda get-function-configuration'

if ([string]::IsNullOrWhiteSpace($apiConfigJson) -or $apiConfigJson -eq 'null') {
    throw "Lambda '$ApiFunction' configuration could not be read."
}
$apiConfig = $apiConfigJson | ConvertFrom-Json
$revisionId = [string]$apiConfig.RevisionId
if ([string]::IsNullOrWhiteSpace($revisionId)) {
    throw "Lambda '$ApiFunction' has no RevisionId."
}
if ($null -eq $apiConfig.Variables) {
    throw "Lambda '$ApiFunction' has no Environment.Variables object."
}

$originalApiVariables = Convert-PropertiesToHashtable $apiConfig.Variables
$desiredApiVariables = @{}
foreach ($key in $originalApiVariables.Keys) {
    $desiredApiVariables[$key] = $originalApiVariables[$key]
}
$desiredApiVariables['ODPT_API_TOKEN'] = $token
$legacyAliasExisted = $desiredApiVariables.ContainsKey('ODPT_API_KEY')
if ($legacyAliasExisted) {
    $desiredApiVariables['ODPT_API_KEY'] = $token
}

$environmentPayload = @{ Variables = $desiredApiVariables } | ConvertTo-Json -Depth 5 -Compress
$tempEnvironmentFile = Join-Path ([System.IO.Path]::GetTempPath()) (
    'toeigo-odpt-env-' + [guid]::NewGuid().ToString('N') + '.json'
)

try {
    [System.IO.File]::WriteAllText(
        $tempEnvironmentFile,
        $environmentPayload,
        [System.Text.UTF8Encoding]::new($false)
    )

    aws lambda update-function-configuration `
        --region $Region `
        --function-name $ApiFunction `
        --revision-id $revisionId `
        --environment "file://$tempEnvironmentFile" `
        --output json | Out-Null
    Assert-LastExitCode 'aws lambda update-function-configuration'

    aws lambda wait function-updated `
        --region $Region `
        --function-name $ApiFunction
    Assert-LastExitCode 'aws lambda wait function-updated'
}
finally {
    Remove-Item -LiteralPath $tempEnvironmentFile -Force -ErrorAction SilentlyContinue
}

# Verify the API Lambda retained every unrelated environment variable exactly.
$installedApiEnvironmentJson = aws lambda get-function-configuration `
    --region $Region `
    --function-name $ApiFunction `
    --query 'Environment.Variables' `
    --output json
Assert-LastExitCode 'verify API Lambda environment'
$installedApiEnvironmentObject = $installedApiEnvironmentJson | ConvertFrom-Json
$installedApiVariables = Convert-PropertiesToHashtable $installedApiEnvironmentObject

if ($installedApiVariables.Count -ne $desiredApiVariables.Count) {
    throw "Lambda '$ApiFunction' environment variable count changed unexpectedly."
}
foreach ($key in $desiredApiVariables.Keys) {
    if (-not $installedApiVariables.ContainsKey($key)) {
        throw "Lambda '$ApiFunction' lost environment variable '$key'."
    }
    if ($installedApiVariables[$key] -ne $desiredApiVariables[$key]) {
        throw "Lambda '$ApiFunction' environment variable '$key' changed unexpectedly."
    }
}
Write-Host "Verified preserved environment on Lambda: $ApiFunction"
if ($legacyAliasExisted) {
    Write-Host 'Updated existing legacy ODPT_API_KEY alias to the same new credential.'
}

# Update the CloudFormation parameter instead of directly editing the managed
# refresh Lambda. This prevents the next stack deployment from restoring an old
# token from the stack parameter.
$stackPayload = @{
    StackName = $RefreshStack
    UsePreviousTemplate = $true
    Capabilities = @('CAPABILITY_IAM')
    Parameters = @(
        @{
            ParameterKey = 'OdptApiToken'
            ParameterValue = $token
        }
    )
} | ConvertTo-Json -Depth 6 -Compress
$tempStackFile = Join-Path ([System.IO.Path]::GetTempPath()) (
    'toeigo-odpt-stack-' + [guid]::NewGuid().ToString('N') + '.json'
)

$stackUpdateStarted = $false
try {
    [System.IO.File]::WriteAllText(
        $tempStackFile,
        $stackPayload,
        [System.Text.UTF8Encoding]::new($false)
    )

    $stackUpdateOutput = @(
        aws cloudformation update-stack `
            --region $Region `
            --cli-input-json "file://$tempStackFile" `
            --output json 2>&1
    )
    $stackUpdateExitCode = $LASTEXITCODE
    if ($stackUpdateExitCode -eq 0) {
        $stackUpdateStarted = $true
    }
    elseif (($stackUpdateOutput -join "`n") -match 'No updates are to be performed') {
        Write-Host 'CloudFormation refresh stack already has the requested configuration.'
    }
    else {
        throw "aws cloudformation update-stack failed with exit code $stackUpdateExitCode."
    }

    if ($stackUpdateStarted) {
        aws cloudformation wait stack-update-complete `
            --region $Region `
            --stack-name $RefreshStack
        Assert-LastExitCode 'aws cloudformation wait stack-update-complete'
    }
}
finally {
    Remove-Item -LiteralPath $tempStackFile -Force -ErrorAction SilentlyContinue
}

$refreshFunction = (aws cloudformation describe-stack-resource `
    --region $Region `
    --stack-name $RefreshStack `
    --logical-resource-id RefreshFunction `
    --query 'StackResourceDetail.PhysicalResourceId' `
    --output text).Trim()
Assert-LastExitCode 'aws cloudformation describe-stack-resource'
if ([string]::IsNullOrWhiteSpace($refreshFunction) -or $refreshFunction -eq 'None') {
    throw "Could not resolve RefreshFunction from stack '$RefreshStack'."
}

foreach ($functionName in @($ApiFunction, $refreshFunction)) {
    $installedToken = aws lambda get-function-configuration `
        --region $Region `
        --function-name $functionName `
        --query 'Environment.Variables.ODPT_API_TOKEN' `
        --output text
    Assert-LastExitCode "verify ODPT_API_TOKEN on $functionName"
    if ($installedToken -ne $token) {
        throw "ODPT_API_TOKEN verification failed on Lambda '$functionName'."
    }
    Write-Host "Verified ODPT_API_TOKEN on Lambda: $functionName"
}

Write-Host 'ODPT token rotation completed successfully.'
