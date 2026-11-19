@echo off
setlocal enabledelayedexpansion
title DesktopSuite Launcher

cd /d "%~dp0"

echo ========================================================
echo   DesktopSuite - Windows 7 / 8 / 10 / 11 Launcher
echo ========================================================

:: 1. Ensure Windows 7 API path compatibility DLL is present in application root and _internal
if not exist "api-ms-win-core-path-l1-1-0.dll" (
    if exist "assets\bin\api-ms-win-core-path-l1-1-0.dll" (
        echo [*] Installing Windows 7 path compatibility DLL...
        copy /y "assets\bin\api-ms-win-core-path-l1-1-0.dll" "api-ms-win-core-path-l1-1-0.dll" >nul
    )
)
if exist "_internal" (
    if not exist "_internal\api-ms-win-core-path-l1-1-0.dll" (
        if exist "assets\bin\api-ms-win-core-path-l1-1-0.dll" (
            copy /y "assets\bin\api-ms-win-core-path-l1-1-0.dll" "_internal\api-ms-win-core-path-l1-1-0.dll" >nul
        )
    )
)

:: 2. Check for Visual C++ 2015-2022 Runtime
if not exist "%SystemRoot%\System32\vcruntime140.dll" (
    if not exist "vcruntime140.dll" (
        echo [!] Microsoft Visual C++ Redistributable is missing.
        echo [*] Downloading and installing required Visual C++ runtime...
        powershell -Command "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; (New-Object Net.WebClient).DownloadFile('https://aka.ms/vs/17/release/vc_redist.x64.exe', '%TEMP%\vc_redist.x64.exe')"
        if exist "%TEMP%\vc_redist.x64.exe" (
            echo [*] Installing runtime silently...
            "%TEMP%\vc_redist.x64.exe" /install /quiet /norestart
        )
    )
)

:: 3. Launch DesktopSuite
echo [*] Launching DesktopSuite...
if exist "DesktopSuite.exe" (
    start "" "DesktopSuite.exe" %*
) else (
    python src\main.py %*
)

exit /b 0
