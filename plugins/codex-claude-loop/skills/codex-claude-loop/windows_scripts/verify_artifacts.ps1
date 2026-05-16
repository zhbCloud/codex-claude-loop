param(
  [string]$RunId = "",
  [string]$ArtifactRoot = ""
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$skillRoot = Split-Path -Parent $scriptRoot
$pythonScript = Join-Path $skillRoot "scripts\verify_artifacts.py"

if (-not (Test-Path -LiteralPath $pythonScript)) {
  throw "Missing verify runtime: $pythonScript"
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
$runtimeArgs = @($pythonScript)
if ($RunId) {
  $runtimeArgs += @("--run-id", $RunId)
}
if ($ArtifactRoot) {
  $runtimeArgs += @("--artifact-root", $ArtifactRoot)
}

$pythonExe = $pythonCommand[0]
if ($pythonCommand.Count -gt 1) {
  $pythonPrefixArgs = @($pythonCommand[1..($pythonCommand.Count - 1)])
  & $pythonExe @pythonPrefixArgs @runtimeArgs
} else {
  & $pythonExe @runtimeArgs
}
exit $LASTEXITCODE
