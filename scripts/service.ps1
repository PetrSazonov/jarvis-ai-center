param(
    [ValidateSet("dev", "prod")]
    [string]$Profile = "dev"
)

$python = if (Test-Path ".\venv\Scripts\python.exe") { ".\venv\Scripts\python.exe" } else { "python" }

& $python scripts/run_web_service.py --profile $Profile @args
