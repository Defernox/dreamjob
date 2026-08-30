# ============================================================
#  DreamJob - lancement quotidien
#    .\dev.ps1
#  Ouvre deux fenetres (API + interface) et le navigateur.
#  Pour tout arreter : fermer les deux fenetres.
# ============================================================
$ErrorActionPreference = "Stop"
$racine = $PSScriptRoot

$PORT_API = 8000
$PORT_INTERFACE = 5173
$PORT_OLLAMA = 11434

function Test-Port {
  param([int]$Port)
  # On lit la table TCP au lieu d'ouvrir une connexion, et ce n'est pas un
  # detail : Vite n'ecoute que sur ::1 (boucle locale IPv6) quand l'API ecoute
  # sur 127.0.0.1. Or PowerShell 5.1 s'appuie sur .NET Framework, ou
  # « New-Object TcpClient » cree une socket IPv4 SEULE - elle ne peut donc
  # joindre ::1, quelle que soit la facon d'ecrire l'adresse. La sonde
  # declarait l'interface morte alors qu'elle repondait, et un second
  # lancement demarrait un Vite en double sur le port 5174.
  #
  # Get-NetTCPConnection ignore la famille d'adresses et repond immediatement,
  # la ou Test-NetConnection met plusieurs secondes sur un port ferme.
  return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-Port {
  param([int]$Port, [int]$Secondes = 60)
  # On attend que le port REPONDE, au lieu de dormir un temps fixe : sur un
  # demarrage a froid, Vite met plus de cinq secondes et le navigateur
  # s'ouvrait sur une page morte.
  $limite = (Get-Date).AddSeconds($Secondes)
  while ((Get-Date) -lt $limite) {
    if (Test-Port -Port $Port) { return $true }
    Start-Sleep -Milliseconds 400
  }
  return $false
}

function Start-Fenetre {
  param([string]$Titre, [string]$Dossier, [string]$Commande)
  Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$Dossier'; `$host.UI.RawUI.WindowTitle = '$Titre'; $Commande"
  )
}

if (-not (Test-Path "$racine\backend\.venv")) {
  Write-Host "Environnement Python absent. Lancez d'abord :  .\setup.cmd" -ForegroundColor Red
  Read-Host "Appuyez sur Entree pour fermer"
  exit 1
}
if (-not (Test-Path "$racine\frontend\node_modules")) {
  Write-Host "Dependances de l'interface absentes. Lancez d'abord :  .\setup.cmd" -ForegroundColor Red
  Read-Host "Appuyez sur Entree pour fermer"
  exit 1
}

# Ollama : le moteur qui redige les lettres. Il demarre normalement avec la
# session, mais il lui arrive de tomber - et l'application se lance alors sans
# que rien ne le signale, jusqu'a ce qu'une lettre echoue. On le releve.
# Son absence n'est jamais bloquante : le CV, le scan et le score n'en ont pas
# besoin, et le bandeau de l'interface annonce deja le mode degrade.
if (-not (Test-Port -Port $PORT_OLLAMA)) {
  $ollama = Get-Command ollama -ErrorAction SilentlyContinue
  if ($ollama) {
    Write-Host "Demarrage d'Ollama       -> redaction des lettres" -ForegroundColor Cyan
    Start-Process -FilePath $ollama.Source -ArgumentList "serve" -WindowStyle Hidden
    if (-not (Wait-Port -Port $PORT_OLLAMA -Secondes 20)) {
      Write-Host "Ollama n'a pas demarre : les lettres seront indisponibles." -ForegroundColor Yellow
    }
  } else {
    Write-Host "Ollama introuvable : les lettres seront indisponibles." -ForegroundColor Yellow
  }
}

# Deja lance ? On ouvre simplement le navigateur. Sans ce controle, un second
# double-clic sur le raccourci demarrait deux serveurs de plus, dont l'un
# echouait sur un port occupe - et l'utilisateur se retrouvait avec quatre
# fenetres dont deux en erreur.
$apiVivante = Test-Port -Port $PORT_API
$interfaceVivante = Test-Port -Port $PORT_INTERFACE

if ($apiVivante -and $interfaceVivante) {
  Write-Host "DreamJob tourne deja - ouverture de l'interface." -ForegroundColor Green
  Start-Process "http://localhost:$PORT_INTERFACE"
  exit 0
}

if (-not $apiVivante) {
  Write-Host "Demarrage de l'API       -> http://127.0.0.1:$PORT_API/docs" -ForegroundColor Cyan
  Start-Fenetre -Titre "DreamJob - API" -Dossier "$racine\backend" `
    -Commande ".\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port $PORT_API"
} else {
  Write-Host "API deja en ecoute sur le port $PORT_API." -ForegroundColor DarkGray
}

if (-not $interfaceVivante) {
  # npm.cmd et non npm : PowerShell prefere le shim npm.ps1, que l'ExecutionPolicy
  # par defaut de Windows refuse d'executer.
  Write-Host "Demarrage de l'interface -> http://localhost:$PORT_INTERFACE" -ForegroundColor Cyan
  Start-Fenetre -Titre "DreamJob - Interface" -Dossier "$racine\frontend" `
    -Commande "npm.cmd run dev"
} else {
  Write-Host "Interface deja en ecoute sur le port $PORT_INTERFACE." -ForegroundColor DarkGray
}

Write-Host "Attente du demarrage..." -ForegroundColor DarkGray
if (Wait-Port -Port $PORT_INTERFACE -Secondes 90) {
  Start-Process "http://localhost:$PORT_INTERFACE"
  Write-Host ""
  Write-Host "DreamJob est lance. L'interface s'ouvre dans votre navigateur." -ForegroundColor Green
} else {
  # Message explicite plutot qu'une fenetre qui se ferme sans rien dire : le
  # raccourci masque cette console, l'utilisateur n'aurait aucune trace.
  Write-Host ""
  Write-Host "L'interface n'a pas repondu en 90 secondes." -ForegroundColor Red
  Write-Host "Regardez la fenetre 'DreamJob - Interface' : elle porte l'erreur." -ForegroundColor Yellow
  Read-Host "Appuyez sur Entree pour fermer"
}
