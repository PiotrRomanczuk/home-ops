# sample-gpu.ps1 — emit one JSON line with current AMD GPU util/VRAM + top-N
# Designed to be called every ~30s from win10-watcher.py. Uses Windows built-in
# perf counters; no external tools. Temperature is not exposed by these
# counters and is left absent — see docs/adr/2026-06-07-no-grafana.md and
# win10-watcher Phase G notes.
#
# The dGPU LUID is auto-detected each run: adapter LUIDs are assigned by
# Windows and change across reboots/driver updates, so a hardcoded value
# eventually goes stale (that failure mode left gpu_pct NULL for weeks).
# GPU_LUID now acts as a preference, not a requirement — if set but absent
# from the live counter instances, detection falls through to the adapter
# with the most dedicated memory in use (the iGPU reports ~0; the desktop
# alone keeps >1 GB resident on the dGPU).
#
# Env vars (all optional):
#   GPU_LUID           preferred dedicated-GPU LUID fragment (auto-detected if unset/stale)
#   VRAM_TOTAL_MB      card VRAM in MB (default: 12288 for RX 7700 XT)
#   TOP_N              top processes by GPU dedicated memory (default: 10)
#
# Output: single-line JSON on stdout; non-zero exit code on counter failure.
[CmdletBinding()]
param(
    [string]$Luid = $(if ($env:GPU_LUID) { $env:GPU_LUID } else { '' }),
    [int]$VramTotalMb = $(if ($env:VRAM_TOTAL_MB) { [int]$env:VRAM_TOTAL_MB } else { 12288 }),
    [int]$TopN = $(if ($env:TOP_N) { [int]$env:TOP_N } else { 10 })
)

$ErrorActionPreference = 'Stop'

function Resolve-GpuLuid {
    param($preferred)
    $instances = (Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage' -MaxSamples 1).CounterSamples
    if (-not $instances) { throw 'no GPU Adapter Memory counter instances' }
    if ($preferred) {
        $hit = $instances | Where-Object { $_.Path -like "*$preferred*" } | Select-Object -First 1
        if ($hit) { return $preferred }
    }
    $top = $instances | Sort-Object CookedValue -Descending | Select-Object -First 1
    if ($top.Path -match '\(([^)]+)\)') { return $matches[1] }
    throw "cannot parse LUID from counter path: $($top.Path)"
}

function Get-GpuComputePct {
    param($luid)
    # MAX across compute engines on the dedicated GPU. Matches the convention
    # nvidia-smi uses for GPU Utilization (0-100), not a sum (which can exceed
    # 100 on multi-engine GPUs). Skip 3D/copy/video — Ollama lands on compute.
    # Engine instances only exist while processes hold GPU contexts, so an
    # empty/missing counter set means idle, not failure.
    try {
        $samples = (Get-Counter '\GPU Engine(*engtype_compute*)\Utilization Percentage' -MaxSamples 1).CounterSamples |
            Where-Object { $_.Path -like "*$luid*" }
    } catch { return 0.0 }
    if (-not $samples) { return 0.0 }
    [math]::Round(($samples | Measure-Object CookedValue -Maximum).Maximum, 1)
}

function Get-GpuVramMb {
    param($luid)
    $s = (Get-Counter "\GPU Adapter Memory($luid)\Dedicated Usage" -MaxSamples 1).CounterSamples
    if (-not $s) { return 0 }
    [int]($s[0].CookedValue / 1MB)
}

function Get-TopGpuMem {
    param($luid, $n)
    $rows = (Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -MaxSamples 1).CounterSamples |
        Where-Object { $_.Path -like "*$luid*" -and $_.CookedValue -gt 0 } |
        Sort-Object CookedValue -Descending |
        Select-Object -First $n
    $out = @()
    foreach ($r in $rows) {
        $pid_ = if ($r.Path -match 'pid_(\d+)_') { [int]$matches[1] } else { 0 }
        $name = '?'
        if ($pid_ -gt 0) {
            $proc = Get-Process -Id $pid_ -ErrorAction SilentlyContinue
            if ($proc) { $name = $proc.ProcessName }
        }
        $out += [PSCustomObject]@{
            pid  = $pid_
            name = $name
            mb   = [int]($r.CookedValue / 1MB)
        }
    }
    ,$out  # comma-prefix forces array shape even when single element
}

try {
    $resolvedLuid = Resolve-GpuLuid -preferred $Luid
    $vramMb  = Get-GpuVramMb -luid $resolvedLuid
    $gpuPct  = Get-GpuComputePct -luid $resolvedLuid
    $topMem  = Get-TopGpuMem -luid $resolvedLuid -n $TopN
    $sample = [PSCustomObject]@{
        gpu_pct       = $gpuPct
        vram_used_mb  = $vramMb
        vram_total_mb = $VramTotalMb
        vram_pct      = if ($VramTotalMb -gt 0) { [math]::Round($vramMb / $VramTotalMb * 100, 1) } else { $null }
        top_gpu_mem   = $topMem
        luid          = $resolvedLuid
        sampled_at    = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    }
    $sample | ConvertTo-Json -Compress -Depth 4
} catch {
    [Console]::Error.WriteLine("sample-gpu.ps1 failed: $_")
    exit 1
}
