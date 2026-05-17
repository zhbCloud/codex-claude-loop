param(
  [Parameter(Mandatory = $true)]
  [string]$TaskFile,

  [ValidateSet("implementation", "rework")]
  [string]$TaskMode = "implementation",

  [ValidateSet("auto", "fast", "strict")]
  [string]$WorkMode = "auto",

  [ValidateSet("PrimaryReuse", "PrimaryAnchor", "ParallelPool")]
  [string]$SessionMode = "PrimaryReuse",

  [Parameter(Mandatory = $true)]
  [string]$WorkflowId,

  [Parameter(Mandatory = $true)]
  [string]$TaskId,

  [Parameter(Mandatory = $true)]
  [ValidateSet("planner", "implementer", "researcher", "reviewer", "final-verifier")]
  [string]$Role,

  [string]$SessionKey = "",
  [string]$Scope = "",
  [switch]$AllowParallel,
  [ValidateSet("light", "full")]
  [string]$ValidationPhase = "light",
  [string]$ReviewForTaskId = "",
  [ValidateSet("", "spec", "quality")]
  [string]$ReviewKind = "",
  [string[]]$DependsOn = @(),
  [string[]]$AllowedPath = @(),
  [string[]]$ValidationCommand = @(),
  [string[]]$Tests = @(),
  [string]$ArtifactRoot = "",
  [string]$Model = "",
  [string]$NamePrefix = "codex-claude-loop",
  [int]$Round = 1,
  [int]$MaxRound = 3,
  [int]$MaxParallel = 5,
  [int]$LeaseTtlSeconds = 7200,
  [int]$LeaseWaitSeconds = 60,
  [int]$MaxRetryCount = 1,
  [switch]$BypassPermissions,
  [switch]$DryRun,
  [switch]$StartOnly,
  [switch]$WaitForCompletion
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillRoot = Split-Path -Parent $scriptRoot
$pythonScript = Join-Path $skillRoot "scripts\delegate_to_claude.py"

if (-not (Test-Path -LiteralPath $pythonScript)) {
  throw "Missing delegate runtime: $pythonScript"
}

function Resolve-Python {
  if ($env:PYTHON -and (Get-Command $env:PYTHON -ErrorAction SilentlyContinue)) {
    return @($env:PYTHON)
  }
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    return @($python.Source)
  }
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    return @($py.Source, "-3")
  }
  throw "Python was not found. Install Python 3 or set the PYTHON environment variable."
}

$pythonCommand = @(Resolve-Python)
$runtimeArgs = @(
  $pythonScript,
  "--task-file", $TaskFile,
  "--task-mode", $TaskMode,
  "--work-mode", $WorkMode,
  "--session-mode", $SessionMode,
  "--workflow-id", $WorkflowId,
  "--task-id", $TaskId,
  "--role", $Role,
  "--validation-phase", $ValidationPhase,
  "--round", $Round,
  "--max-round", $MaxRound,
  "--max-parallel", $MaxParallel,
  "--lease-ttl-seconds", $LeaseTtlSeconds,
  "--lease-wait-seconds", $LeaseWaitSeconds,
  "--max-retry-count", $MaxRetryCount,
  "--name-prefix", $NamePrefix
)

if ($SessionKey) {
  $runtimeArgs += @("--session-key", $SessionKey)
}
if ($Scope) {
  $runtimeArgs += @("--scope", $Scope)
}
if ($ReviewForTaskId) {
  $runtimeArgs += @("--review-for-task-id", $ReviewForTaskId)
}
if ($ReviewKind) {
  $runtimeArgs += @("--review-kind", $ReviewKind)
}
if ($ArtifactRoot) {
  $runtimeArgs += @("--artifact-root", $ArtifactRoot)
}
if ($Model) {
  $runtimeArgs += @("--model", $Model)
}
foreach ($item in $AllowedPath) {
  $runtimeArgs += @("--allowed-path", $item)
}
foreach ($item in $ValidationCommand) {
  $runtimeArgs += @("--validation-command", $item)
}
foreach ($item in $DependsOn) {
  $runtimeArgs += @("--depends-on", $item)
}
foreach ($item in $Tests) {
  $runtimeArgs += @("--tests", $item)
}
if ($AllowParallel) {
  $runtimeArgs += "--allow-parallel"
}
if ($BypassPermissions) {
  $runtimeArgs += "--bypass-permissions"
}
if ($DryRun) {
  $runtimeArgs += "--dry-run"
}
if (-not $WaitForCompletion) {
  $StartOnly = $true
}
if ($StartOnly) {
  $runtimeArgs += "--prepare-only"
}

$pythonExe = $pythonCommand[0]
$pythonPrefixArgs = @()
if ($pythonCommand.Count -gt 1) {
  $pythonPrefixArgs = @($pythonCommand[1..($pythonCommand.Count - 1)])
}

if ($StartOnly) {
  $capturedOutput = & $pythonExe @pythonPrefixArgs @runtimeArgs 2>&1
  $prepareExitCode = $LASTEXITCODE
  foreach ($line in $capturedOutput) {
    Write-Output $line
  }
  if ($prepareExitCode -ne 0) {
    exit $prepareExitCode
  }

  $configPath = ""
  $statusPath = ""
  foreach ($line in $capturedOutput) {
    $text = [string]$line
    if ($text -match '^ConfigPath:\s*(.+)$') {
      $configPath = $Matches[1].Trim()
    }
    if ($text -match '^StatusPath:\s*(.+)$') {
      $statusPath = $Matches[1].Trim()
    }
  }
  if (-not $configPath) {
    throw "Delegate prepare step did not return ConfigPath."
  }

  $configName = [System.IO.Path]::GetFileNameWithoutExtension($configPath)
  $runId = $configName.Substring("config_".Length)
  $artifactDir = Split-Path -Parent $configPath
  $workerLog = Join-Path $artifactDir "worker_$runId.log"
  $workerErrLog = Join-Path $artifactDir "worker_$runId.err.log"
  $workerArgs = @()
  $workerArgs += $pythonPrefixArgs
  $workerArgs += @($pythonScript, "--worker-config", $configPath)
  $process = Start-Process -FilePath $pythonExe -ArgumentList $workerArgs -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru -RedirectStandardOutput $workerLog -RedirectStandardError $workerErrLog

  if ($statusPath -and (Test-Path -LiteralPath $statusPath)) {
    $status = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
    $status | Add-Member -NotePropertyName workerPid -NotePropertyValue $process.Id -Force
    $status | Add-Member -NotePropertyName workerLogPath -NotePropertyValue $workerLog -Force
    $status | Add-Member -NotePropertyName workerErrorLogPath -NotePropertyValue $workerErrLog -Force
    $status | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $statusPath -Encoding utf8
  }

  $payload = [ordered]@{
    state = "started"
    runId = $runId
    workflowId = $WorkflowId
    taskId = $TaskId
    role = $Role
    statusPath = $statusPath
    configPath = $configPath
    workerPid = $process.Id
    workerLog = $workerLog
    workerErrorLog = $workerErrLog
  }
  $payload | ConvertTo-Json -Depth 10 -Compress | Write-Output
  exit 0
}

$capturedOutput = if ($pythonPrefixArgs.Count -gt 0) {
  & $pythonExe @pythonPrefixArgs @runtimeArgs 2>&1
} else {
  & $pythonExe @runtimeArgs 2>&1
}
$finalExitCode = $LASTEXITCODE
foreach ($line in $capturedOutput) {
  Write-Output $line
}
$runId = ""
$statusValue = if ($finalExitCode -eq 0) { "completed" } else { "failed" }
$statusPath = ""
foreach ($line in $capturedOutput) {
  $text = [string]$line
  if ($text -match '^RunId:\s*(.+)$') {
    $runId = $Matches[1].Trim()
  }
  if ($text -match '^Status:\s*(.+)$') {
    $statusValue = $Matches[1].Trim()
  }
  if ($text -match '^StatusPath:\s*(.+)$') {
    $statusPath = $Matches[1].Trim()
  }
}
$state = if ($statusValue -eq "completed") { "completed" } else { "failed" }
$payload = [ordered]@{
  state = $state
  runId = $runId
  workflowId = $WorkflowId
  taskId = $TaskId
  role = $Role
  status = $statusValue
  statusPath = $statusPath
  exitCode = $finalExitCode
}
$payload | ConvertTo-Json -Depth 10 -Compress | Write-Output
exit $finalExitCode
