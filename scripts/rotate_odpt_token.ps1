<#
.SYNOPSIS
  Rotate the ODPT API token used by the existing Tokyo AWS runtime without
  replacing unrelated Lambda environment variables.

.DESCRIPTION
  - Requires ODPT_API_TOKEN in the current PowerShell environment.
  - Validates the token against the authenticated ODPT API before touching AWS.
  - Updates only ODPT_API_TOKEN on the Tokyo API Lambda while preserving every
    other environment variable exactly.
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

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    throw 'Required command was not found: aws'
}

$token = $env:ODPT_API_TOKEN
if ([string]::IsNullOrWhiteSpace($token)) {
    throw 'ODPT_API_TOKEN is required in the current environment.'
}

# Validate the exact token first. Do not rotate AWS to an unusable credential.
$validationUri = 'https://api.odpt.org/api/v4/odpt:BusstopPole'
$validationResponse = Invoke-WebRequest `
    -Uri $validationUri `
    -Method Get `
    -Body @{
        'odpt:operator' = 'odpt.Operator:Toei'
        'acl:consumerKey' = $token
    } `
    -TimeoutSec 20
if ($validationResponse.StatusCode -ne 200) {
    throw "ODPT token validation failed with HTTP $($validationResponse.StatusCode)."
}
Write-Host 'ODPT token validation: OK'

# Fetch the current API Lambda environment and preserve every unrelated value.
$apiEnvironmentJson = aws lambda get-function-configuration `
    --region $Region `
    --function-name $ApiFunction `
    --query 'Environment.Variables' `
    --output json
Assert-LastExitCode 'aws lambda get-function-configuration'

if ([string]::IsNullOrWhiteSpace($apiEnvironmentJson) -or $apiEnvironmentJson -eq 'null') {
    throw "Lambda '$ApiFunction' has no Environment.Variables object."
}

$apiEnvironmentObject = $apiEnvironmentJson | ConvertFrom-Json
$apiVariables = @{}
foreach ($property in $apiEnvironmentObject.PSObject.Properties) {
    $apiVariables[$property.Name] = [string]$property.Value
}
$apiVariables['ODPT_API_TOKEN'] = $token

$environmentPayload = @{ Variables = $apiVariables } | ConvertTo-Json -Depth 5 -Compress
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

try {
    [System.IO.File]::WriteAllText(
        $tempStackFile,
        $stackPayload,
        [System.Text.UTF8Encoding]::new($false)
    )

    aws cloudformation update-stack `
        --region $Region `
        --cli-input-json "file://$tempStackFile" `
        --output json | Out-Null
    Assert-LastExitCode 'aws cloudformation update-stack'

    aws cloudformation wait stack-update-complete `
        --region $Region `
        --stack-name $RefreshStack
    Assert-LastExitCode 'aws cloudformation wait stack-update-complete'
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
