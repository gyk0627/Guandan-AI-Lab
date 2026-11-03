# GPU Engine sampler - same data source as Windows Task Manager ("Performance > GPU").
# Task Manager reads the "GPU Engine" perf counters, which are split by engine type
# (3D, Compute_0, Compute_1, Copy, VideoDecode...). nvidia-smi's utilization.gpu is a
# different metric, so the two can disagree.
#
# CSV: time,3D,Compute,Copy,Video,Other  (percent of time busy, summed per engine type)
# ASCII only: Windows PowerShell reads .ps1 as ANSI.
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [int]$Seconds = 600,
    [int]$IntervalMs = 200
)

$end = (Get-Date).AddSeconds($Seconds)

while ((Get-Date) -lt $end) {
    try {
        $samples = (Get-Counter '\GPU Engine(*)\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples
        $sum = @{ threeD = 0.0; compute = 0.0; copy = 0.0; video = 0.0; other = 0.0 }

        if ($samples) {
            foreach ($sample in $samples) {
                $instance = $sample.InstanceName
                $value = $sample.CookedValue

                if ($instance -match 'engtype_3D') { $sum.threeD += $value }
                elseif ($instance -match 'engtype_Compute') { $sum.compute += $value }
                elseif ($instance -match 'engtype_Copy') { $sum.copy += $value }
                elseif ($instance -match 'engtype_Video') { $sum.video += $value }
                else { $sum.other += $value }
            }
        }

        Add-Content -LiteralPath $Out -Value ("{0},{1:F1},{2:F1},{3:F1},{4:F1},{5:F1}" -f (Get-Date -Format 'HH:mm:ss.fff'), $sum.threeD, $sum.compute, $sum.copy, $sum.video, $sum.other)
    } catch {
    }

    Start-Sleep -Milliseconds $IntervalMs
}
