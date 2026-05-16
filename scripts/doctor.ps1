param(
  [switch]$SkipCodexCli,
  [switch]$SkipCodexRead
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
$ExpectedMarketplacePath = Join-Path $RepoRoot '.agents/plugins/marketplace.json'
$ExpectedPluginRelPath = './plugins/codex-claude-loop'
$ExpectedPluginDir = Join-Path $RepoRoot 'plugins/codex-claude-loop'
$ExpectedManifestPath = Join-Path $ExpectedPluginDir '.codex-plugin/plugin.json'
$ExpectedSkillPath = Join-Path $ExpectedPluginDir 'skills/codex-claude-loop/SKILL.md'

$failures = New-Object System.Collections.Generic.List[string]
$warnings = New-Object System.Collections.Generic.List[string]

function Add-Failure {
  param([string]$Message)
  $failures.Add($Message) | Out-Null
}

function Add-Warning {
  param([string]$Message)
  $warnings.Add($Message) | Out-Null
}

function Test-PathInside {
  param(
    [string]$BasePath,
    [string]$ChildPath
  )

  $base = [System.IO.Path]::GetFullPath($BasePath).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
  $child = [System.IO.Path]::GetFullPath($ChildPath).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
  return $child.StartsWith($base, [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-GitChangedFiles {
  $gitCommand = Get-Command git -ErrorAction SilentlyContinue
  if ($null -eq $gitCommand) {
    return @()
  }

  try {
    $diffFiles = & git -C $RepoRoot diff --name-only 2>$null
    $stagedFiles = & git -C $RepoRoot diff --cached --name-only 2>$null
    return @($diffFiles + $stagedFiles) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique
  } catch {
    return @()
  }
}

Write-Host 'Codex Claude Loop doctor'
Write-Host "Repository: $RepoRoot"

if (-not $IsWindows) {
  Add-Failure 'This plugin is Windows-only. Run installation and runtime checks on Windows.'
} else {
  Write-Host '[ok] Windows detected'
}

if (-not (Test-Path -LiteralPath $ExpectedMarketplacePath -PathType Leaf)) {
  Add-Failure "Missing marketplace file: $ExpectedMarketplacePath"
} else {
  Write-Host '[ok] Marketplace file exists'
}

$marketplace = $null
if (Test-Path -LiteralPath $ExpectedMarketplacePath -PathType Leaf) {
  try {
    $marketplace = Get-Content -LiteralPath $ExpectedMarketplacePath -Raw | ConvertFrom-Json
  } catch {
    Add-Failure "Marketplace JSON is invalid: $($_.Exception.Message)"
  }
}

if ($null -ne $marketplace) {
  if ($marketplace.name -ne 'codex-claude-loop') {
    Add-Failure "Marketplace name should be 'codex-claude-loop', found '$($marketplace.name)'."
  } else {
    Write-Host '[ok] Marketplace name is codex-claude-loop'
  }

  $plugin = @($marketplace.plugins | Where-Object { $_.name -eq 'codex-claude-loop' }) | Select-Object -First 1
  if ($null -eq $plugin) {
    Add-Failure "Marketplace does not contain plugin 'codex-claude-loop'."
  } else {
    Write-Host '[ok] Marketplace contains codex-claude-loop'

    if ($plugin.source.source -ne 'local') {
      Add-Failure "Plugin source should be 'local', found '$($plugin.source.source)'."
    }

    $path = [string]$plugin.source.path
    if ([string]::IsNullOrWhiteSpace($path)) {
      Add-Failure 'Plugin source path must not be empty.'
    } elseif (-not $path.StartsWith('./')) {
      Add-Failure "Plugin source path must start with './', found '$path'."
    } elseif ($path -eq './' -or $path -eq '.') {
      Add-Failure "Plugin source path must point to a non-empty child directory, found '$path'."
    } elseif ($path -ne $ExpectedPluginRelPath) {
      Add-Failure "Plugin source path should be '$ExpectedPluginRelPath', found '$path'."
    } else {
      Write-Host "[ok] Plugin source path is $ExpectedPluginRelPath"
    }

    if ($path -match '\.\.') {
      Add-Failure "Plugin source path must stay inside the marketplace root and must not contain '..': $path"
    }
  }
}

if (-not (Test-Path -LiteralPath $ExpectedPluginDir -PathType Container)) {
  Add-Failure "Missing plugin directory: $ExpectedPluginDir"
} else {
  Write-Host '[ok] Plugin directory exists'
  if (-not (Test-PathInside -BasePath $RepoRoot -ChildPath $ExpectedPluginDir)) {
    Add-Failure 'Plugin directory must stay inside the marketplace repository root.'
  }
}

if (-not (Test-Path -LiteralPath $ExpectedManifestPath -PathType Leaf)) {
  Add-Failure "Missing plugin manifest: $ExpectedManifestPath"
} else {
  Write-Host '[ok] Plugin manifest exists'
  try {
    $manifest = Get-Content -LiteralPath $ExpectedManifestPath -Raw | ConvertFrom-Json
    if ($manifest.name -ne 'codex-claude-loop') {
      Add-Failure "Plugin manifest name should be 'codex-claude-loop', found '$($manifest.name)'."
    }
    if ($manifest.skills -ne './skills/') {
      Add-Failure "Plugin manifest skills path should be './skills/', found '$($manifest.skills)'."
    }
    if ($manifest.interface.defaultPrompt.Count -gt 3) {
      Add-Failure 'Plugin manifest interface.defaultPrompt supports at most 3 prompts.'
    }
    foreach ($prompt in @($manifest.interface.defaultPrompt)) {
      if (($prompt | Measure-Object -Character).Characters -gt 128) {
        Add-Failure "Plugin manifest defaultPrompt exceeds 128 characters: $prompt"
      }
    }
  } catch {
    Add-Failure "Plugin manifest JSON is invalid: $($_.Exception.Message)"
  }
}

if (-not (Test-Path -LiteralPath $ExpectedSkillPath -PathType Leaf)) {
  Add-Failure "Missing skill file: $ExpectedSkillPath"
} else {
  Write-Host '[ok] Skill file exists'
}

$readmePaths = @(
  (Join-Path $RepoRoot 'README.md'),
  (Join-Path $RepoRoot 'README-ZH.md')
)

foreach ($readmePath in $readmePaths) {
  if (-not (Test-Path -LiteralPath $readmePath -PathType Leaf)) {
    Add-Failure "Missing README file: $readmePath"
    continue
  }

  $readmeLines = Get-Content -LiteralPath $readmePath
  $readme = $readmeLines -join "`n"
  if ($readme.Contains('.\skills\codex-claude-loop\windows_scripts') -or
      $readme.Contains('`skills/codex-claude-loop/windows_scripts/`')) {
    Add-Failure "README contains stale root skill path: $readmePath"
  }
  foreach ($line in $readmeLines) {
    if ($line.Contains('"path": "./"') -and
        -not $line.Contains('Do not use') -and
        -not $line.Contains('不要')) {
      Add-Failure "README still recommends invalid marketplace path './': $readmePath"
      break
    }
  }
  if ($readme.Contains('repository root because') -or
      $readme.Contains('插件位于仓库根目录') -or
      $readme.Contains('指向当前仓库根目录')) {
    Add-Failure "README still describes the plugin as living at the repository root: $readmePath"
  }
}

Write-Host '[ok] README stale-path checks completed'

$changedFiles = @(Get-GitChangedFiles)
if ($changedFiles.Count -gt 0) {
  $capabilityPatterns = @(
    '^plugins/codex-claude-loop/skills/',
    '^plugins/codex-claude-loop/hooks/',
    '^plugins/codex-claude-loop/\.codex-plugin/plugin\.json$'
  )
  $manifestPath = 'plugins/codex-claude-loop/.codex-plugin/plugin.json'
  $capabilityChanged = $false
  foreach ($file in $changedFiles) {
    $normalizedFile = $file.Replace('\', '/')
    foreach ($pattern in $capabilityPatterns) {
      if ($normalizedFile -match $pattern) {
        $capabilityChanged = $true
        break
      }
    }
    if ($capabilityChanged) {
      break
    }
  }

  $manifestChanged = $changedFiles | Where-Object { $_.Replace('\', '/') -eq $manifestPath } | Select-Object -First 1
  if ($capabilityChanged -and -not $manifestChanged) {
    Add-Warning "Plugin capability files changed. Check whether $manifestPath version should be bumped before release."
  } elseif ($capabilityChanged) {
    Write-Host '[ok] Plugin capability changes include plugin.json; confirm version bump is intentional'
  }
}

if (-not $SkipCodexCli) {
  $codexCommand = Get-Command codex -ErrorAction SilentlyContinue
  if ($null -eq $codexCommand) {
    Add-Failure 'Codex CLI was not found on PATH. Install Codex CLI before installing this plugin.'
  } else {
    Write-Host "[ok] Codex CLI found: $($codexCommand.Source)"
    try {
      $version = (& codex --version 2>&1 | Select-Object -First 1)
      Write-Host "[ok] Codex CLI version: $version"
    } catch {
      Add-Failure "Failed to run 'codex --version': $($_.Exception.Message)"
    }
  }
}

if (-not $SkipCodexCli -and -not $SkipCodexRead -and (Get-Command codex -ErrorAction SilentlyContinue)) {
  $nodeCommand = Get-Command node -ErrorAction SilentlyContinue
  if ($null -eq $nodeCommand) {
    Add-Warning 'Node.js was not found, skipping optional Codex app-server plugin/read validation.'
  } else {
    $nodeScript = @'
const { spawn } = require('child_process');
const marketplacePath = process.argv[2] || process.argv[1];
const child = spawn('codex', ['app-server', '--listen', 'stdio://'], { shell: true, windowsHide: true });
let out = '';
let err = '';
const timeout = setTimeout(() => {
  child.kill();
  console.error('Timed out waiting for codex app-server.');
  process.exitCode = 2;
}, 7000);
child.stdout.on('data', d => { out += d.toString(); });
child.stderr.on('data', d => { err += d.toString(); });
function send(obj) { child.stdin.write(JSON.stringify(obj) + '\n'); }
send({ id: 1, method: 'initialize', params: { clientInfo: { name: 'codex-claude-loop-doctor', version: '0' }, capabilities: { experimentalApi: true } } });
setTimeout(() => send({ id: 2, method: 'plugin/read', params: { marketplacePath, pluginName: 'codex-claude-loop' } }), 500);
setTimeout(() => child.stdin.end(), 2500);
child.on('close', () => {
  clearTimeout(timeout);
  const lines = out.trim().split(/\r?\n/).filter(Boolean);
  const response = lines.map(line => { try { return JSON.parse(line); } catch { return null; } }).find(msg => msg && msg.id === 2);
  if (!response) {
    console.error('No plugin/read response from codex app-server.');
    if (err) console.error(err);
    process.exit(3);
  }
  if (response.error) {
    console.error(response.error.message || JSON.stringify(response.error));
    process.exit(4);
  }
  const skillCount = (((response.result || {}).plugin || {}).skills || []).length;
  console.log(`plugin/read ok; skills=${skillCount}`);
});
'@

    try {
      $readOutput = $nodeScript | node - $ExpectedMarketplacePath 2>&1
      if ($LASTEXITCODE -ne 0) {
        Add-Failure "Codex app-server plugin/read failed: $($readOutput -join ' ')"
      } else {
        Write-Host "[ok] Codex app-server can read plugin: $($readOutput -join ' ')"
      }
    } catch {
      Add-Failure "Codex app-server plugin/read failed: $($_.Exception.Message)"
    }
  }
}

foreach ($warning in $warnings) {
  Write-Warning $warning
}

if ($failures.Count -gt 0) {
  Write-Host ''
  Write-Host 'Doctor failed:' -ForegroundColor Red
  foreach ($failure in $failures) {
    Write-Host " - $failure" -ForegroundColor Red
  }
  exit 1
}

Write-Host ''
Write-Host 'Doctor passed.' -ForegroundColor Green
