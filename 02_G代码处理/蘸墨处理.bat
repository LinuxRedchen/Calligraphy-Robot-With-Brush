@echo off
chcp 65001 >nul
setlocal
set "SCRIPT=%~dp0add_ink.sh"

rem ============================================================
rem 自动定位 bash.exe，避免写死某台机器的安装路径
rem   1) 环境变量 BASH_PATH（手动指定优先）
rem   2) Git for Windows 常见安装位置
rem   3) 系统 PATH 里的 bash
rem 都找不到时提示安装 Git for Windows
rem ============================================================
set "BASH="
if defined BASH_PATH if exist "%BASH_PATH%" set "BASH=%BASH_PATH%"
if not defined BASH if exist "%ProgramFiles%\Git\bin\bash.exe" set "BASH=%ProgramFiles%\Git\bin\bash.exe"
if not defined BASH if exist "%ProgramFiles(x86)%\Git\bin\bash.exe" set "BASH=%ProgramFiles(x86)%\Git\bin\bash.exe"
if not defined BASH if exist "%LocalAppData%\Programs\Git\bin\bash.exe" set "BASH=%LocalAppData%\Programs\Git\bin\bash.exe"
if not defined BASH if exist "E:\Git\bin\bash.exe" set "BASH=E:\Git\bin\bash.exe"
if not defined BASH for /f "delims=" %%i in ('where bash 2^>nul') do if not defined BASH set "BASH=%%i"

if not defined BASH (
    echo.
    echo [错误] 没找到 bash.exe
    echo.
    echo 本脚本需要 Git for Windows 提供的 bash，请任选一种方式：
    echo   1. 安装 Git for Windows：https://git-scm.com/download/win
    echo   2. 设置环境变量 BASH_PATH，指向你的 bash.exe，例如：
    echo      setx BASH_PATH "D:\Git\bin\bash.exe"
    echo.
    pause
    exit /b 1
)

if "%~1"=="" (
    echo.
    echo 用法：把导出的 .gcode 文件直接拖到这个图标上
    echo 会自动生成同名 _蘸墨.gcode 文件
    echo.
    echo 也可以手动： 蘸墨处理.bat  文件路径.gcode
    echo.
    echo 当前使用的 bash：%BASH%
    echo.
    pause
    exit /b
)

"%BASH%" "%SCRIPT%" "%~1"
echo.
pause
endlocal
