@echo off
chcp 65001 >nul
setlocal
echo ================================
echo    EJECUTANDO APLICACIÓN
echo ================================
echo.

REM Cambiar al directorio del script (carpeta raíz del proyecto)
pushd "%~dp0"

if not exist backend (
    echo ERROR: No se encontró la carpeta backend en el proyecto.
    pause >nul
    popd
    exit /b 1
)

if not exist venv\Scripts\python.exe (
    echo 1. Creando entorno virtual...
    py -3 -m venv venv
)

if not exist venv\Scripts\python.exe (
    echo ERROR: No se pudo crear el entorno virtual.
    pause
    popd
    exit /b 1
)

echo 2. Verificando Python...
venv\Scripts\python.exe --version

echo 3. Instalando dependencias...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install -r backend\requirements.txt

echo 4. Ejecutando aplicación...
echo ================================
venv\Scripts\python.exe app.py

echo.
echo ================================
echo Presiona cualquier tecla para salir...
pause >nul
popd