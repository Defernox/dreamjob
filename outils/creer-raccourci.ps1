# ============================================================
#  Cree le raccourci « DreamJob » sur le Bureau.
#  A relancer si le projet est deplace : le raccourci pointe sur un chemin fixe.
# ============================================================
$ErrorActionPreference = "Stop"
$racine = Split-Path -Parent $PSScriptRoot
$icone = Join-Path $PSScriptRoot "dreamjob.ico"

if (-not (Test-Path $icone)) {
  Write-Host "Icone absente, generation..." -ForegroundColor DarkGray
  & "$racine\backend\.venv\Scripts\python.exe" "$PSScriptRoot\icone.py"
}

# [Environment]::GetFolderPath plutot que "$env:USERPROFILE\Desktop" : le Bureau
# peut etre redirige vers OneDrive, et le raccourci atterrirait dans un dossier
# que l'utilisateur ne voit pas.
$bureau = [Environment]::GetFolderPath("Desktop")
$lien = Join-Path $bureau "DreamJob.lnk"

$shell = New-Object -ComObject WScript.Shell
$raccourci = $shell.CreateShortcut($lien)

# On vise powershell.exe et non dev.cmd : cela permet -WindowStyle Hidden, qui
# masque la console du lanceur. Les deux fenetres des serveurs, elles, restent
# visibles - elles portent les logs, et les fermer arrete l'application.
$raccourci.TargetPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$raccourci.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$racine\dev.ps1`""
$raccourci.WorkingDirectory = $racine
$raccourci.IconLocation = "$icone,0"
$raccourci.Description = "Lance DreamJob (API + interface) et ouvre le navigateur"
$raccourci.WindowStyle = 7          # demarre reduit : rien ne clignote a l'ecran
$raccourci.Save()

Write-Host ""
Write-Host "Raccourci cree : $lien" -ForegroundColor Green
Write-Host "Double-cliquez dessus pour lancer DreamJob." -ForegroundColor Green
Write-Host ""
Write-Host "Deux fenetres s'ouvriront (API et interface) : ce sont les serveurs." -ForegroundColor DarkGray
Write-Host "Les fermer arrete l'application." -ForegroundColor DarkGray
