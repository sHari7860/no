from pathlib import Path
import os

# Base del proyecto (carpeta donde está config.py, es decir /app dentro de Docker)
BASE_DIR = Path(__file__).resolve().parent

# Frontend: dentro de Docker los templates y static están en /app/templates y /app/static
FRONTEND_TEMPLATES = BASE_DIR / 'templates'
FRONTEND_STATIC = BASE_DIR / 'static'

# Uploads
UPLOAD_FOLDER = BASE_DIR / 'uploads'

# Data directory
DATA_DIR = BASE_DIR / 'data'
SQLITE_DB = DATA_DIR / 'matriculas.db'

# Asegurar directorios existan
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)