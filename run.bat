@echo off
chcp 65001 >nul
echo ================================
echo    EJECUTANDO APLICACIÓN
echo ================================
echo.

cd /d "C:\Users\Sharyk Forero\Downloads\web"

echo 1. Limpiando entorno anterior...
rmdir /s /q venv 2>nul

echo 2. Creando entorno virtual...
"C:\Users\Sharyk Forero\AppData\Local\Programs\Python\Python312\python.exe" -m venv venv

if not exist venv (
    echo ERROR: No se pudo crear el entorno
    pause
    exit /b 1
)

echo 3. Verificando Python...
venv\Scripts\python.exe --version

echo 4. Instalando dependencias...
venv\Scripts\pip.exe install sqlalchemy==2.0.30 flask pandas

echo 5. Ejecutando aplicación...
echo ================================
venv\Scripts\python.exe app.py

echo.
echo ================================
echo Presiona cualquier tecla para salir...
pause >nul