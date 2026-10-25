@echo off
rem Baut dist\psyrip\psyrip.exe (Ordner-Variante) inkl. bin\ffmpeg.exe
rem und – falls Inno Setup 6 installiert ist – den Installer installer_out\psyrip-setup-<Version>.exe.
rem ffmpeg-Quelle: Umgebungsvariable FFMPEG_DIR (Ordner mit ffmpeg.exe) oder das ffmpeg aus PATH.
setlocal
cd /d "%~dp0"
pip install pyinstaller
python tools\make_icon.py
pyinstaller --noconfirm --windowed --name psyrip --icon psyrip\assets\psyrip.ico --add-data "psyrip\assets;psyrip\assets" --collect-submodules psyrip --hidden-import lxml.etree --hidden-import PIL.Image --exclude-module PySide6.QtNetwork --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick psyrip_launcher.py || exit /b 1

rem --- Ungenutzte Qt-Teile entfernen (psyrip braucht nur QtCore/QtGui/QtWidgets): ~40 MB ---
set "QT=dist\psyrip\_internal\PySide6"
for %%f in (opengl32sw.dll Qt6Quick.dll Qt6Qml.dll Qt6QmlModels.dll Qt6QmlMeta.dll Qt6QmlWorkerScript.dll Qt6VirtualKeyboard.dll Qt6Pdf.dll Qt6Network.dll QtNetwork.pyd) do if exist "%QT%\%%f" del "%QT%\%%f"
for %%f in (imageformats\qpdf.dll platforminputcontexts\qtvirtualkeyboardplugin.dll) do if exist "%QT%\plugins\%%f" del "%QT%\plugins\%%f"
for %%d in (tls networkinformation) do if exist "%QT%\plugins\%%d" rmdir /s /q "%QT%\plugins\%%d"

rem --- ffmpeg mitliefern (echter Ordner, nicht der winget-Link) ---
if not defined FFMPEG_DIR for /f "delims=" %%i in ('python -c "import shutil,os;p=shutil.which('ffmpeg');print(os.path.dirname(os.path.realpath(p)) if p else '')"') do set "FFMPEG_DIR=%%i"
if not exist "%FFMPEG_DIR%\ffmpeg.exe" (
  echo FEHLER: ffmpeg.exe nicht gefunden. FFMPEG_DIR setzen oder ffmpeg installieren ^(winget install Gyan.FFmpeg^).
  exit /b 1
)
if not exist dist\psyrip\bin mkdir dist\psyrip\bin
copy /y "%FFMPEG_DIR%\ffmpeg.exe" dist\psyrip\bin\ >nul || exit /b 1
rem ffprobe wird nicht mitgeliefert (würde weitere ~210 MB kosten) – analysis.probe nutzt dann ffmpeg -i
rem Lizenz (GPL) und Quellenhinweis des ffmpeg-Builds mitliefern
if exist "%FFMPEG_DIR%\..\LICENSE" copy /y "%FFMPEG_DIR%\..\LICENSE" dist\psyrip\bin\ffmpeg-LICENSE.txt >nul
if exist "%FFMPEG_DIR%\..\README.txt" copy /y "%FFMPEG_DIR%\..\README.txt" dist\psyrip\bin\ffmpeg-README.txt >nul
echo ffmpeg mitgeliefert aus %FFMPEG_DIR%

rem --- Installer ---
set "ISCC="
for %%p in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do if exist %%p set "ISCC=%%~p"
if not defined ISCC (
  echo Inno Setup 6 nicht gefunden - nur dist\psyrip gebaut. ^(winget install JRSoftware.InnoSetup^)
  exit /b 0
)
for /f "delims=" %%v in ('python -c "import psyrip;print(psyrip.__version__)"') do set "VER=%%v"
"%ISCC%" /Q /DAppVersion=%VER% installer\psyrip.iss || exit /b 1
echo Installer: installer_out\psyrip-setup-%VER%.exe
