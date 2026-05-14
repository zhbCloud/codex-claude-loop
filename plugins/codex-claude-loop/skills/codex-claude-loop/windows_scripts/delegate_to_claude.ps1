param(
  [Parameter(Mandatory = $true)]
  [string]$TaskFile,

  [ValidateSet("implementation", "rework")]
  [string]$TaskMode = "implementation",

  [ValidateSet("PrimaryReuse", "PrimaryAnchor", "ParallelPool")]
  [string]$SessionMode = "PrimaryReuse",

  [string]$SessionKey = "",
  [string[]]$AllowedPath = @(),
  [string[]]$ValidationCommand = @(),
  [string]$ArtifactRoot = "",
  [string]$Model = "",
  [string]$NamePrefix = "codex-claude-loop",
  [int]$Round = 1,
  [int]$MaxRound = 3,
  [int]$MaxParallel = 3,
  [int]$LeaseTtlSeconds = 7200,
  [int]$LeaseWaitSeconds = 60,
  [int]$MaxRetryCount = 1,
  [switch]$BypassPermissions,
  [switch]$DryRun
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

$pythonCommand = Resolve-Python
$runtimeArgs = @(
  $pythonScript,
  "--task-file", $TaskFile,
  "--task-mode", $TaskMode,
  "--session-mode", $SessionMode,
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
if ($BypassPermissions) {
  $runtimeArgs += "--bypass-permissions"
}
if ($DryRun) {
  $runtimeArgs += "--dry-run"
}

if ($pythonCommand.Count -gt 1) {
  & $pythonCommand[0] @($pythonCommand[1..($pythonCommand.Count - 1)]) @runtimeArgs
} else {
  & $pythonCommand[0] @runtimeArgs
}
exit $LASTEXITCODE
