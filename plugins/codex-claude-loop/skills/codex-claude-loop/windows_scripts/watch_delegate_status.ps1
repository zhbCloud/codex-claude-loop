param(
  [string]$RunId = "",
  [string]$WorkflowId = "",
  [string]$ArtifactRoot = "",
  [switch]$Watch,
  [int]$InitialIntervalSeconds = 1,
  [int]$MaxIntervalSeconds = 12,
  [int]$TimeoutSeconds = 0,
  [int]$StreamTailLines = 0
)

$ErrorActionPreference = "Stop"

function Resolve-ArtifactRoot {
  param([string]$ExplicitRoot)
  if ($ExplicitRoot) {
    return [System.IO.Path]::GetFullPath($ExplicitRoot)
  }
  return (Join-Path (Get-Location).Path ".codex\codex_claude_loop\claude-delegate")
}

function Get-LatestRunId {
  param([string]$Root)
  $latest = Get-ChildItem -LiteralPath $Root -Filter "status_*.json" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
  if ($null -eq $latest) {
    throw "No status artifacts found under $Root"
  }
  return $latest.BaseName.Substring("status_".Length)
}

function Read-Status {
  param(
    [string]$Root,
    [string]$Id
  )
  $statusPath = Join-Path $Root "status_$Id.json"
  if (-not (Test-Path -LiteralPath $statusPath -PathType Leaf)) {
    throw "Status artifact not found: $statusPath"
  }
  return Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
}

function Read-Workflow {
  param(
    [string]$Root,
    [string]$Id
  )
  $workflowPath = Join-Path $Root "workflow_$Id.json"
  if (-not (Test-Path -LiteralPath $workflowPath -PathType Leaf)) {
    throw "Workflow artifact not found: $workflowPath"
  }
  return Get-Content -LiteralPath $workflowPath -Raw | ConvertFrom-Json
}

function Format-StatusLine {
  param($Status)
  function Format-Value {
    param($Value)
    if ($null -eq $Value) {
      return "-"
    }
    if ($Value -is [datetime]) {
      return $Value.ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
    }
    if ([string]::IsNullOrWhiteSpace([string]$Value)) {
      return "-"
    }
    return [string]$Value
  }
  $phase = if ($Status.phase) { $Status.phase } else { "-" }
  $updated = Format-Value -Value $Status.updatedAt
  $heartbeat = Format-Value -Value $Status.heartbeatAt
  $records = if ($null -ne $Status.streamRecords) { $Status.streamRecords } else { 0 }
  return "RunId=$($Status.runId) Status=$($Status.status) Phase=$phase UpdatedAt=$updated HeartbeatAt=$heartbeat StreamRecords=$records"
}

function Write-Status {
  param(
    [string]$Root,
    $Status,
    [int]$TailLines
  )
  Write-Output (Format-StatusLine -Status $Status)
  if ($Status.workflowId) {
    Write-Output "WorkflowId=$($Status.workflowId)"
  }
  if ($Status.taskId) {
    Write-Output "TaskId=$($Status.taskId)"
  }
  if ($Status.role) {
    Write-Output "Role=$($Status.role)"
  }
  if ($Status.lastAssistantTextPreview) {
    Write-Output "LastAssistantTextPreview=$($Status.lastAssistantTextPreview)"
  }
  if ($Status.failedReasons -and $Status.failedReasons.Count -gt 0) {
    Write-Output "FailedReasons=$($Status.failedReasons -join '; ')"
  }
  if ($TailLines -gt 0 -and $Status.streamPath -and (Test-Path -LiteralPath $Status.streamPath -PathType Leaf)) {
    Write-Output "StreamTail:"
    Get-Content -LiteralPath $Status.streamPath -Tail $TailLines
  }
}

function Write-WorkflowSummary {
  param(
    [string]$Root,
    [string]$WorkflowId,
    [int]$TailLines
  )
  $workflow = Read-Workflow -Root $Root -Id $WorkflowId
  $runs = @($workflow.runs)
  $total = $runs.Count
  $completed = 0
  $failed = 0
  $running = 0

  Write-Output "WorkflowId=$WorkflowId TotalRuns=$total"

  foreach ($run in $runs) {
    $runId = [string]$run.runId
    $statusValue = [string]$run.status
    $taskId = [string]$run.taskId
    $role = [string]$run.role
    $statusPath = [string]$run.statusPath

    if ($statusPath -and (Test-Path -LiteralPath $statusPath -PathType Leaf)) {
      $statusDoc = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
      $statusValue = [string]$statusDoc.status
      if ($TailLines -gt 0) {
        Write-Status -Root $Root -Status $statusDoc -TailLines $TailLines
        continue
      }
    }

    if ($statusValue -eq "completed") {
      $completed++
    } elseif ($statusValue -eq "failed") {
      $failed++
    } else {
      $running++
    }

    Write-Output "RunId=$runId TaskId=$taskId Role=$role Status=$statusValue"
  }

  Write-Output "WorkflowSummary Completed=$completed Running=$running Failed=$failed"
}

$root = Resolve-ArtifactRoot -ExplicitRoot $ArtifactRoot
$deadline = if ($TimeoutSeconds -gt 0) { (Get-Date).AddSeconds($TimeoutSeconds) } else { $null }
$interval = [Math]::Max(1, $InitialIntervalSeconds)
$maxInterval = [Math]::Max($interval, $MaxIntervalSeconds)

while ($true) {
  if ($WorkflowId) {
    Write-WorkflowSummary -Root $root -WorkflowId $WorkflowId -TailLines $StreamTailLines

    $workflow = Read-Workflow -Root $root -Id $WorkflowId
    $statuses = @($workflow.runs | ForEach-Object { $_.status })
    $hasFailed = $statuses -contains "failed"
    $allFinished = ($statuses.Count -gt 0) -and (@($statuses | Where-Object { $_ -notin @("completed", "failed") }).Count -eq 0)

    if (-not $Watch -or $hasFailed -or $allFinished) {
      if ($hasFailed) {
        exit 1
      }
      break
    }
  } else {
    $runIdToRead = if ($RunId) { $RunId } else { Get-LatestRunId -Root $root }
    $status = Read-Status -Root $root -Id $runIdToRead
    Write-Status -Root $root -Status $status -TailLines $StreamTailLines

    if (-not $Watch -or $status.status -in @("completed", "failed")) {
      if ($status.status -eq "failed") {
        exit 1
      }
      break
    }
  }

  if ($null -ne $deadline -and (Get-Date) -ge $deadline) {
    Write-Output "WatchTimeout=TimeoutSeconds:$TimeoutSeconds"
    exit 2
  }

  Start-Sleep -Seconds $interval
  $interval = [Math]::Min($maxInterval, [Math]::Max($interval + 3, [int]($interval * 1.5)))
}

exit 0
