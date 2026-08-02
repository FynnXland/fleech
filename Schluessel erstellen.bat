@echo off
REM ============================================================================
REM  Fleech - Lizenzschluessel fuer eine Person ausstellen.
REM  Doppelklick genuegt: Name eintippen, fertig. Der Schluessel landet in der
REM  Zwischenablage.
REM
REM  Liegt bewusst im Projekt-Hauptordner statt in packaging/ - man findet sie
REM  nur, wenn sie da liegt, wo man ohnehin hinschaut.
REM ============================================================================
setlocal

REM Konsole auf UTF-8: sonst zerlegt cp850 die Umlaute in eingegebenen Namen,
REM und der Name steckt SIGNIERT im Schluessel - falsche Umlaute = falscher Key.
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

REM Immer relativ zum Ort dieser Datei arbeiten, egal von wo gestartet wird.
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo.
  echo   Die Projekt-Umgebung fehlt: %~dp0.venv
  echo   Diese Datei gehoert in den Fleech-Projektordner - dorthin verschieben
  echo   oder die Umgebung neu anlegen.
  echo.
  pause
  exit /b 1
)

"%PY%" packaging\issue_key.py --frage
set "CODE=%ERRORLEVEL%"

echo.
REM Ohne pause schliesst sich das Fenster beim Doppelklick sofort - samt Schluessel.
pause
exit /b %CODE%
