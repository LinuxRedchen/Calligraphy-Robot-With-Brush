@echo off
chcp 65001 >nul
setlocal
set "BASH=E:\Git\usr\bin\bash.exe"
set "SCRIPT=%~dp0add_ink.sh"

if "%~1"=="" (
    echo.
    echo 用法：把导出的 .gcode 文件直接拖到这个图标上
    echo 会自动生成同名 _蘸墨.gcode 文件
    echo.
    echo 也可以手动： 蘸墨处理.bat  文件路径.gcode
    echo.
    pause
    exit /b
)

"%BASH%" "%SCRIPT%" "%~1"
echo.
pause
endlocal
