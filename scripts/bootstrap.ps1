# Bootstrap (Windows PowerShell)
python -m venv venv

$python = ".\\venv\\Scripts\\python.exe"
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "Created .env from .env.example"
}

Write-Host "Bootstrap completed."
Write-Host "Bot run: .\\scripts\\run.ps1"
Write-Host "Web service run (dev): python scripts\\run_web_service.py --profile dev"
