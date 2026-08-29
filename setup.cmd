@echo off
REM Installation DreamJob (a lancer une seule fois).
REM Voir dev.cmd pour l explication du contournement d ExecutionPolicy.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
