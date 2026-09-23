$ErrorActionPreference = "Stop"

$JevRepository = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDirectory = Join-Path $JevRepository "logs"
New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$LifecycleLog = Join-Path $LogDirectory "jev-lifecycle.jsonl"
$env:JEV_LIFECYCLE_LOG = $LifecycleLog
$env:JEV_ROUTING_CONFIG = Join-Path $JevRepository "routing-config.json"

function Write-LifecycleEvent {
  param(
    [Parameter(Mandatory = $true)][string]$Event,
    [hashtable]$Fields = @{}
  )
  $Record = [ordered]@{
    at = (Get-Date).ToString("o")
    event = $Event
    source = "powershell"
    pid = $PID
  }
  foreach ($Entry in $Fields.GetEnumerator()) {
    $Record[$Entry.Key] = $Entry.Value
  }
  ($Record | ConvertTo-Json -Compress) | Add-Content -LiteralPath $LifecycleLog -Encoding utf8
}

Write-LifecycleEvent "launcher_start"
try {
  $EnvFile = Join-Path $JevRepository ".env"
  $KeyLine = Get-Content -LiteralPath $EnvFile |
    Where-Object { $_ -match "^\s*TYPESAFE_API_KEY\s*=" } |
    Select-Object -First 1
  if (-not $KeyLine) {
    throw "TYPESAFE_API_KEY is missing from $EnvFile"
  }
  $KeyValue = ($KeyLine -split "=", 2)[1].Trim().Trim('"').Trim("'")
  if (-not $KeyValue) {
    throw "TYPESAFE_API_KEY is empty in $EnvFile"
  }
  $env:TYPESAFE_API_KEY = $KeyValue

  # Optional proxy for this service process only; e.g. set JEV_PROXY to
  # http://127.0.0.1:7897 when this host needs the local proxy.
  if ($env:JEV_PROXY) {
    $env:HTTP_PROXY = $env:JEV_PROXY
    $env:HTTPS_PROXY = $env:JEV_PROXY
    $env:ALL_PROXY = $env:JEV_PROXY
  }
  $env:NO_PROXY = "127.0.0.1,localhost"

  $Server = Join-Path $JevRepository "server\jev_server.py"
  $RunStamp = (Get-Date).ToString("yyyyMMdd-HHmmss-fff")
  $StdoutLog = Join-Path $LogDirectory "jev-server-$RunStamp.out.log"
  $StderrLog = Join-Path $LogDirectory "jev-server-$RunStamp.err.log"

  Write-LifecycleEvent "child_start" @{
    stdout = $StdoutLog
    stderr = $StderrLog
  }
  $PreviousErrorActionPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    & "C:\Windows\py.exe" -3.12 $Server 1>> $StdoutLog 2>> $StderrLog
    $ChildExitCode = $LASTEXITCODE
  }
  finally {
    $ErrorActionPreference = $PreviousErrorActionPreference
  }
  Write-LifecycleEvent "child_exit" @{ exit_code = $ChildExitCode }
  exit $ChildExitCode
}
catch {
  Write-LifecycleEvent "launcher_error" @{
    exception_type = $_.Exception.GetType().Name
    message = $_.Exception.Message.Substring(0, [Math]::Min(500, $_.Exception.Message.Length))
  }
  throw
}
