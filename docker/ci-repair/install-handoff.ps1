param(
    [Parameter(Mandatory=$true)][string]$ClaudePath,
    [Parameter(Mandatory=$true)][string]$PolicyPath,
    [Parameter(Mandatory=$true)][string]$PythonPath,
    [Parameter(Mandatory=$true)][string]$InstallDirectory,
    [Parameter(Mandatory=$true)][string]$StorageDirectory
)
$ErrorActionPreference = 'Stop'
$pythonBinary = (Resolve-Path -LiteralPath $PythonPath).Path
& $pythonBinary -c 'import sys; assert sys.version_info[:2] == (3, 14), "Python 3.14 required"'
if ($LASTEXITCODE -ne 0) { throw 'Use Python 3.14 for the handoff launcher.' }
$gitPath = (Get-Command git.exe -ErrorAction Stop).Source
$claudeBinary = (Resolve-Path -LiteralPath $ClaudePath).Path
$installRoot = [IO.Path]::GetFullPath($InstallDirectory)
$storageRoot = [IO.Path]::GetFullPath($StorageDirectory)
$handler = Join-Path $installRoot 'handoff.py'
$key = 'HKCU:\Software\Classes\issueclaw-ci'
$command = '"' + $pythonBinary + '" -I "' + $handler + '" "%1"'
if (Test-Path -LiteralPath $key) {
    $existing = (Get-Item -LiteralPath "$key\shell\open\command").GetValue('')
    if ($existing -ne $command) { throw 'Another issueclaw-ci handler is installed; refusing to replace it.' }
}
New-Item -ItemType Directory -Force -Path $installRoot,$storageRoot | Out-Null
$source = Join-Path $PSScriptRoot '../../src/issueclaw/ci_handoff.py'
Copy-Item -LiteralPath $source -Destination $handler -Force
$policy = Get-Content -Raw -LiteralPath $PolicyPath | ConvertFrom-Json -AsHashtable
$policy.claude=$claudeBinary
$policy.git=$gitPath
$policy.storage=$storageRoot
$policy | ConvertTo-Json |
    Set-Content -LiteralPath (Join-Path $installRoot 'config.json') -Encoding UTF8
New-Item -Path "$key\shell\open\command" -Force | Out-Null
Set-Item -LiteralPath $key -Value 'URL:Issueclaw CI handoff'
New-ItemProperty -LiteralPath $key -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
Set-Item -LiteralPath "$key\shell\open\command" -Value $command
Write-Output "Installed current-user issueclaw-ci URL handler in $installRoot"
Write-Output 'No service, scheduled task, credential copy, or administrator permission is used.'
