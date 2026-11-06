@echo off
setlocal
cd /d "%~dp0"

rem 1) Python 3.12 (versao testada). Se faltar, instala pelo winget (vem com o Windows 10/11).
py -3.12 -c "" >nul 2>&1
if errorlevel 1 (
    echo Python 3.12 nao encontrado. Instalando...
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    echo.
    echo Se a instalacao funcionou, feche esta janela e abra o start_app.bat de novo.
    echo Se falhou, instale o Python 3.12 por https://www.python.org/downloads/ e tente de novo.
    pause
    exit /b 1
)

rem 2) Ambiente isolado do app (.venv) com as versoes exatas do requirements.txt.
if not exist ".venv\Scripts\pythonw.exe" (
    echo Preparando o app pela primeira vez, pode levar alguns minutos...
    py -3.12 -m venv .venv || goto :erro
    rem Atalho "Voila" na Area de Trabalho e no Menu Iniciar, com icone e agrupamento na barra de tarefas.
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_shortcut.ps1" >nul 2>&1
)
fc /b requirements.txt .venv\installed.txt >nul 2>&1
if errorlevel 1 (
    echo Instalando bibliotecas...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt || goto :erro
    copy /y requirements.txt .venv\installed.txt >nul
)

rem 3) Opcional: captura por app especifico. So compila se o .NET SDK estiver instalado.
if not exist "native\ProcessLoopbackCapture\bin\Release\net9.0-windows\ProcessLoopbackCapture.exe" (
    where dotnet >nul 2>&1 && dotnet build "native\ProcessLoopbackCapture" -c Release --nologo -v q >nul 2>&1
)

start "" ".venv\Scripts\pythonw.exe" main.py
exit /b 0

:erro
echo.
echo Falha na instalacao. Veja a mensagem acima.
pause
exit /b 1
