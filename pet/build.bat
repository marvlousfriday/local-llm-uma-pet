@echo off
chcp 65001 >nul
setlocal

rem 上游源码放到 pet/src40/（自行 git clone --branch v4.0）
cd /d "%~dp0src40\Desktop_Gremlin" 2>nul
if errorlevel 1 (
    echo [x] 找不到 src40\Desktop_Gremlin
    echo     git clone --branch v4.0 https://github.com/Kritzkingvoid/Desktop_Gremlin src40
    pause
    exit /b 1
)

set "MSB=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\MSBuild.exe"
if not exist "%MSB%" set "MSB=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\MSBuild.exe"

if not exist "%MSB%" (
    echo [x] 找不到 MSBuild，请先安装 .NET Framework 4.8 Developer Pack
    echo     https://dotnet.microsoft.com/download/dotnet-framework/net48
    pause
    exit /b 1
)

if not exist "C:\Program Files (x86)\Reference Assemblies\Microsoft\Framework\.NETFramework\v4.8" (
    echo [x] 缺少 v4.8 引用程序集（Developer Pack 没装好）
    echo     下载 NDP48-DevPack-ENU.exe 安装后重试：
    echo     https://dotnet.microsoft.com/download/dotnet-framework/net48
    pause
    exit /b 1
)

rem 系统自带 csc 是 C# 5，编不了本项目的 C# 6+ 语法，必须用 Roslyn
set "ROSLYN=%~dp0tools\roslyn\tools"
if not exist "%ROSLYN%\csc.exe" (
    echo [x] 找不到 Roslyn 编译器：%ROSLYN%
    echo.
    echo     获取方式（任选其一）：
    echo     1^) nuget install Microsoft.Net.Compilers -Version 3.11.0 -OutputDirectory tools
    echo     2^) 下载 https://www.nuget.org/api/v2/package/Microsoft.Net.Compilers/3.11.0
    echo        改名为 .zip 解压到 pet\tools\roslyn\
    echo.
    echo     目录结构应为 pet\tools\roslyn\tools\csc.exe
    pause
    exit /b 1
)

echo [1/2] 编译中（Roslyn 编译器）...
"%MSB%" Desktop_Gremlin\Desktop_Gremlin.csproj /p:Configuration=Release /p:CscToolPath="%ROSLYN%" /p:CscToolExe=csc.exe /v:minimal /nologo
if errorlevel 1 (
    echo.
    echo [x] 编译失败，看上面的错误
    pause
    exit /b 1
)

echo.
echo [2/2] 完成，产物：
if exist "Desktop_Gremlin\bin\Release\DesktopGremlin.exe" (
    for %%F in ("Desktop_Gremlin\bin\Release\DesktopGremlin.exe") do echo     %%~fF  %%~zF 字节
) else (
    echo     没找到 exe，检查输出目录
)
echo.
pause
