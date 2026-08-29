# ============================================================
#  DreamJob - lancement quotidien
#    .\dev.ps1
#  Ouvre deux fenetres (API + interface) et le navigateur.
#  Pour tout arreter : fermer les deux fenetres.
# ============================================================
$ErrorActionPreference = "Stop"
$racine = $PSScriptRoot

if (-not (Test-Path "$racine\backend\.venv")) {
  Write-Host "Environnement Python absent. Lancez d'abord :  .\setup.ps1" -ForegroundColor Red
  exit 1
}
if (-not (Test-Path "$racine\frontend\node_modules")) {
  Write-Host "Dependances de l'interface absentes. Lancez d'abord :  .\setup.ps1" -ForegroundColor Red
  exit 1
}

Write-Host "Demarrage de l'API      -> http://127.0.0.1:8000/docs" -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$racine\backend'; " +
  "`$host.UI.RawUI.WindowTitle = 'DreamJob - API'; " +
  ".\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
)

# npm.cmd et non npm : PowerShell prefere le shim npm.ps1, que l'ExecutionPolicy
# par defaut de Windows refuse d'executer.
Write-Host "Demarrage de l'interface -> http://localhost:5173" -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
  "-NoExit", "-Command",
  "Set-Location '$racine\frontend'; " +
  "`$host.UI.RawUI.WindowTitle = 'DreamJob - Interface'; " +
  "npm.cmd run dev"
)

Start-Sleep -Seconds 5
Start-Process "http://localhost:5173"
Write-Host ""
Write-Host "DreamJob est lance. L'interface s'ouvre dans votre navigateur." -ForegroundColor Green
