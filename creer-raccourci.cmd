@echo off
REM Cree le raccourci DreamJob sur le Bureau.
REM
REM Windows bloque par defaut l execution des .ps1 (ExecutionPolicy). Les .cmd,
REM eux, ne sont pas concernes : ce fichier appelle le .ps1 avec un contournement
REM valable pour ce seul processus. Aucun reglage de securite n est modifie.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0outils\creer-raccourci.ps1" %*
pause
