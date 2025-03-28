@echo off
:: 设置控制台编码为UTF-8
chcp 65001 > nul
echo ==== Qwen-Omni 语音助手 Windows 打包工具 ====
echo.

:: 检查当前目录
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\..\"
cd /d "%PROJECT_ROOT%"

:: 检测Python环境
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo 错误: 未找到Python，请确保已安装Python并添加到PATH环境变量
    pause
    exit /b 1
)

:: 尝试使用uv
where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    echo 发现uv包管理器，将使用uv进行依赖安装
    set USE_UV=1
) else (
    echo 未找到uv包管理器，将使用pip进行依赖安装
    set USE_UV=0
)

:: 确保pip可用
if %USE_UV% equ 0 (
    python -m ensurepip --upgrade >nul 2>nul
    python -m pip --version >nul 2>nul
    if %ERRORLEVEL% neq 0 (
        echo 警告: pip不可用，将尝试使用内置的ensurepip模块安装
        python -m ensurepip --default-pip
        if %ERRORLEVEL% neq 0 (
            echo 错误: 无法安装pip
            pause
            exit /b 1
        )
    )
)

:: 安装PyInstaller（如果尚未安装）
echo 检查PyInstaller是否已安装...
python -c "import PyInstaller" >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo 正在安装PyInstaller...
    if %USE_UV% equ 1 (
        uv pip install pyinstaller
    ) else (
        python -m pip install pyinstaller
    )
    
    if %ERRORLEVEL% neq 0 (
        echo 错误: PyInstaller安装失败
        pause
        exit /b 1
    )
)

:: 设置UTF-8环境变量
set PYTHONIOENCODING=utf-8

:: 执行打包脚本
echo 正在启动打包过程...
python "%SCRIPT_DIR%build.py"

:: 等待用户确认
if %ERRORLEVEL% neq 0 (
    echo.
    echo 打包过程遇到错误，请查看上方错误信息
) else (
    echo.
    echo 打包完成! 请查看dist目录
)

pause 