@echo off
REM Lance demarrer.ps1 en contournant la strategie d'execution PowerShell.
REM Double-cliquez sur ce fichier pour demarrer l'application.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0demarrer.ps1" %*
