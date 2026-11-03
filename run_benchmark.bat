@echo off
rem GuanDan Benchmark: measure this machine (CPU sim, GPU inference, training, export, pipeline).
rem Double-click to run. Extra args are passed through, e.g.:
rem   run_benchmark.bat --modules cpu,inference
rem   run_benchmark.bat --compare evaluation\benchmark_v1_baseline.json
setlocal
cd /d "C:\Users\qq165\Documents\deepseek-harness\default-workspace\GuanDan-AI-Lab"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Python venv not found. The path may be wrong.
  pause
  exit /b 1
)

echo ============================================================
echo  GuanDan Benchmark
echo ============================================================
echo.

".venv\Scripts\python.exe" -X utf8 -u -m tools.benchmark_suite %*

echo.
echo Done. Press any key to close.
pause
