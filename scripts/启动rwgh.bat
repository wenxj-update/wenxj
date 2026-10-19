@echo off
chcp 65001 >nul
title 任务规划仿真系统 (rwgh_FZ)

REM ============================================================
REM  启动脚本: 任务规划仿真系统 (rwgh_FZ)
REM  双击运行;关闭窗口或点击应用关闭按钮即可退出。
REM ============================================================

REM ---- 工程根目录(脚本所在路径的上级) ----
set "PROJ_ROOT=d:\wenxj\6-software\rwgh_FZ\rwgh_FZ_test"

REM ---- Python 解释器(优先用 anaconda,回退 PATH) ----
set "PY_EXE=C:\ProgramData\anaconda3\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=python"

REM ---- 进入工程根目录(避免相对路径漂移) ----
cd /d "%PROJ_ROOT%" || (
    echo [错误] 无法进入工程目录: %PROJ_ROOT%
    pause
    exit /b 1
)

REM ---- 设置 PYTHONPATH(src 目录 → rwgh 包可导入) ----
set "PYTHONPATH=%PROJ_ROOT%\src;%PYTHONPATH%"

REM ---- 工作目录(配置文件查找根) ----
set "RWGH_CONFIG=config/app.yaml"
set "RWGH_FORMATS=config/formats"

echo ================================================================
echo  任务规划仿真系统 (rwgh_FZ)
echo  工程目录: %PROJ_ROOT%
echo  Python:    %PY_EXE%
echo ================================================================
echo.

REM ---- 启动 GUI ----
"%PY_EXE%" -m rwgh.app

if errorlevel 1 (
    echo.
    echo [应用已退出,返回码: %errorlevel%]
    pause
)
