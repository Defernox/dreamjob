@echo off
REM Lanceur DreamJob.
REM
REM Windows bloque par defaut l execution des .ps1 (ExecutionPolicy). Les .cmd,
REM eux, ne sont pas concernes : ce fichier appelle dev.ps1 avec un contournement
REM valable pour ce seul processus. Aucun reglage de securite n est modifie.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %*
