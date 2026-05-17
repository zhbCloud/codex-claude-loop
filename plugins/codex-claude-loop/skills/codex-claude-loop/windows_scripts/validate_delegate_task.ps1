param(
  [Parameter(Mandatory = $true)]
  [string]$TaskFile,

  [string[]]$Tests = @()
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillRoot = Split-Path -Parent $scriptRoot
$pythonScript = Join-Path $skillRoot "scripts\validate_delegate_task.py"

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
$pythonExe = $pythonCommand[0]
$pythonPrefixArgs = @()
if ($pythonCommand.Count -gt 1) {
  $pythonPrefixArgs = @($pythonCommand[1..($pythonCommand.Count - 1)])
}

$runtimeArgs = @($pythonScript, "--task-file", $TaskFile)
foreach ($item in $Tests) {
  $runtimeArgs += @("--tests", $item)
}

& $pythonExe @pythonPrefixArgs @runtimeArgs
exit $LASTEXITCODE
