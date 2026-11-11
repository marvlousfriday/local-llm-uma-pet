@echo off
setlocal
REM ---- CHANGE THESE THREE PLACEHOLDERS BEFORE USE ----
set "PY=@PYTHON311@\python.exe"
set "INPUT=@UMAVIEWER_DIR@\build\StandaloneWindows64\Screenshots"
set "TARGET=@PET_DIR@\SpriteSheet\Gremlins\MarvelousSunday"
echo Input  : %INPUT%
echo Target : %TARGET%
echo.
REM Remove --no-fill to auto-fill unrecorded actions with the new character's
REM idle frames (same sheet size, so config frame counts stay valid).
"%PY%" "%~dp0gif_to_sheet.py" "%INPUT%" "%TARGET%" --no-fill
echo.
echo Done. Press any key to close.
pause >nul
