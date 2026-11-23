@echo off
REM Arranque no PC servidor. Os tecnicos abrem no browser: http://IP-DO-PC:8501
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERRO] Python nao encontrado. Instale o Python 3.11+ e marque "Add Python to PATH".
    pause
    exit /b 1
)

if not exist ".streamlit\secrets.toml" (
    echo [ERRO] Falta o ficheiro .streamlit\secrets.toml
    echo Copie .streamlit\secrets.toml.exemplo para .streamlit\secrets.toml e preencha.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo A criar ambiente...
    python -m venv .venv
    if errorlevel 1 ( echo [ERRO] Falha ao criar o ambiente. & pause & exit /b 1 )
)

if not exist ".venv\Scripts\streamlit.exe" (
    echo A instalar bibliotecas, aguarde...
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERRO] Falha a instalar as bibliotecas. Veja a mensagem acima.
        pause
        exit /b 1
    )
)

".venv\Scripts\python.exe" -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --server.maxUploadSize 200
pause
