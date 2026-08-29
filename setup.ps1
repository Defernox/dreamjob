# ============================================================
#  DreamJob - installation (a lancer UNE SEULE FOIS)
#    .\setup.ps1
# ============================================================
$ErrorActionPreference = "Stop"
$racine = $PSScriptRoot

Write-Host ""
Write-Host "== DreamJob : installation ==" -ForegroundColor Cyan
Write-Host ""

# --- 1. Environnement Python ---
Write-Host "[1/4] Environnement Python..." -ForegroundColor Yellow
Set-Location "$racine\backend"
if (-not (Test-Path ".\.venv")) { py -3 -m venv .venv }
.\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.\.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
Write-Host "      OK" -ForegroundColor Green

# --- 2. Base de donnees ---
Write-Host "[2/4] Base de donnees (migrations)..." -ForegroundColor Yellow
.\.venv\Scripts\alembic.exe upgrade head
Write-Host "      OK" -ForegroundColor Green

# --- 3. Dependances front ---
Write-Host "[3/4] Dependances de l'interface..." -ForegroundColor Yellow
Set-Location "$racine\frontend"
npm.cmd install --silent
Write-Host "      OK" -ForegroundColor Green

# --- 4. Fichier .env ---
Write-Host "[4/4] Fichier .env..." -ForegroundColor Yellow
Set-Location $racine
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
$contenuEnv = Get-Content ".env" -Raw
if ($contenuEnv -match "ANTHROPIC_API_KEY=\s*(\r?\n|$)") {
  Write-Host "      ATTENTION : ANTHROPIC_API_KEY est vide dans .env" -ForegroundColor Red
  Write-Host "      Sans cle : pas d'import de CV, pas de lettre de motivation." -ForegroundColor Red
} else {
  Write-Host "      OK" -ForegroundColor Green
}

Write-Host ""
Write-Host "Installation terminee. Lancez maintenant :  .\dev.ps1" -ForegroundColor Cyan
Write-Host ""
