# Run bot (Windows PowerShell)
$python = if (Test-Path ".\\venv\\Scripts\\python.exe") { ".\\venv\\Scripts\\python.exe" } else { "python" }
& $python bot.py
