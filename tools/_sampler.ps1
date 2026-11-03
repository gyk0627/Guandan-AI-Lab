# Resource sampler.
# CSV columns:
#   time, cpu_total_pct, free_mem_mb, gpu_util_pct, gpu_mem_mb, power_w, temp_c, gpu_clock_mhz, per_core_cpu(| separated)
# ASCII only: Windows PowerShell reads .ps1 as ANSI, non-ASCII would break parsing.
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$Seconds = 600,
    [int]$IntervalMs = 500
)

$end = (Get-Date).AddSeconds($Seconds)

while ((Get-Date) -lt $end) {
    try {
        $cpu = (Get-Counter '\Processor(_Total)\% Processor Time' -ErrorAction SilentlyContinue).CounterSamples.CookedValue
        $cores = (Get-Counter '\Processor(*)\% Processor Time' -ErrorAction SilentlyContinue).CounterSamples
        $coreText = ''

        if ($cores) {
            $values = @()

            foreach ($core in $cores) {
                if ($core.InstanceName -ne '_total') {
                    $values += ('{0:F1}' -f $core.CookedValue)
                }
            }

            $coreText = ($values -join '|')
        }

        $free = (Get-Counter '\Memory\Available MBytes' -ErrorAction SilentlyContinue).CounterSamples.CookedValue
        $gpuLine = & nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw,temperature.gpu,clocks.current.graphics --format=csv,noheader,nounits 2>$null

        if ($gpuLine) {
            $parts = $gpuLine -split ','
            $gpuUtil = $parts[0].Trim()
            $gpuMem = $parts[1].Trim()
            $power = $parts[2].Trim()
            $temp = $parts[3].Trim()
            $clock = $parts[4].Trim()
        } else {
            $gpuUtil = ''
            $gpuMem = ''
            $power = ''
            $temp = ''
            $clock = ''
        }

        Add-Content -LiteralPath $Out -Value ("{0},{1:F1},{2:F0},{3},{4},{5},{6},{7},{8}" -f (Get-Date -Format 'HH:mm:ss.fff'), $cpu, $free, $gpuUtil, $gpuMem, $power, $temp, $clock, $coreText)
    } catch {
    }

    Start-Sleep -Milliseconds $IntervalMs
}
