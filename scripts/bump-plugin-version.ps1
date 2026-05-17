param(
  [ValidateSet('patch', 'minor', 'major')]
  [string]$Part = 'patch',
  [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$ManifestPath = Join-Path $RepoRoot 'plugins/codex-claude-loop/.codex-plugin/plugin.json'
$ManifestRelPath = 'plugins/codex-claude-loop/.codex-plugin/plugin.json'

$CapabilityPatterns = @(
  '^plugins/codex-claude-loop/skills/',
  '^plugins/codex-claude-loop/hooks/',
  '^plugins/codex-claude-loop/\.codex-plugin/plugin\.json$'
)

function Get-GitChangedFiles {
  $gitCommand = Get-Command git -ErrorAction SilentlyContinue
  if ($null -eq $gitCommand) {
    throw 'git was not found on PATH.'
  }

  $diffFiles = & git -C $RepoRoot diff --name-only
  $stagedFiles = & git -C $RepoRoot diff --cached --name-only
  return @($diffFiles + $stagedFiles) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
}

function Test-CapabilityChange {
  param([string[]]$Files)

  foreach ($file in $Files) {
    $normalized = $file.Replace('\', '/')
    foreach ($pattern in $CapabilityPatterns) {
      if ($normalized -match $pattern) {
        return $true
      }
    }
  }
  return $false
}

function Add-Version {
  param(
    [string]$Version,
    [string]$Part
  )

  $parts = $Version.Split('.')
  if ($parts.Count -ne 3) {
    throw "Plugin version must be semantic x.y.z, found '$Version'."
  }

  $major = [int]$parts[0]
  $minor = [int]$parts[1]
  $patch = [int]$parts[2]

  switch ($Part) {
    'major' {
      $major += 1
      $minor = 0
      $patch = 0
    }
    'minor' {
      $minor += 1
      $patch = 0
    }
    default {
      $patch += 1
    }
  }

  return "$major.$minor.$patch"
}

if (-not (Test-Path -LiteralPath $ManifestPath -PathType Leaf)) {
  throw "Missing plugin manifest: $ManifestPath"
}

$changedFiles = @(Get-GitChangedFiles)
$hasCapabilityChange = Test-CapabilityChange -Files $changedFiles

if (-not $hasCapabilityChange) {
  Write-Host 'No plugin capability changes detected; version unchanged.'
  exit 0
}

$manifestChanged = $changedFiles | Where-Object { $_.Replace('\', '/') -eq $ManifestRelPath } | Select-Object -First 1
if ($manifestChanged) {
  Write-Host 'Plugin manifest already changed; assuming version was handled intentionally.'
  exit 0
}

$manifestText = Get-Content -LiteralPath $ManifestPath -Raw
$manifest = $manifestText | ConvertFrom-Json
$oldVersion = [string]$manifest.version
$newVersion = Add-Version -Version $oldVersion -Part $Part

if ($CheckOnly) {
  Write-Error "Plugin capability files changed but $ManifestRelPath version was not bumped. Suggested next version: $newVersion"
}

$updatedText = ($manifestText -replace '"version"\s*:\s*"[^"]+"', ('"version": "' + $newVersion + '"')).TrimEnd("`r", "`n") + "`n"
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllText($ManifestPath, $updatedText, $utf8NoBom)
Write-Host "Bumped plugin version: $oldVersion -> $newVersion"
