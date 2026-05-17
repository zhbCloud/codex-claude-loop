$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

& git -C $RepoRoot config core.hooksPath .githooks
Write-Host 'Configured git core.hooksPath=.githooks'
