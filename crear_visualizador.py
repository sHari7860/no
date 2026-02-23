#!/usr/bin/env python3
"""
Script para crear un usuario con rol 'visualizador'.
El visualizador puede ver Dashboard, Datos y Exportar CSV, pero NO puede:
- Importar Excel
- Ver Logs de auditoría
"""

from werkzeug.security import generate_password_hash
import psycopg2
import os

# Configuración de BD
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:123456@localhost:5432/UNITEC")

# Datos del nuevo usuario
USERNAME = "visualizador"
PASSWORD = "visualizador123"
NOMBRE_COMPLETO = "Usuario Visualizador"
ROL = "visualizador"

def crear_usuario():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        # Generar hash de la contraseña
        password_hash = generate_password_hash(PASSWORD)
        
        # Insertar usuario
        cursor.execute(
            '''
            INSERT INTO usuarios (username, password_hash, nombre_completo, rol, activo)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (username) DO UPDATE SET
                password_hash = EXCLUDED.password_hash,
                nombre_completo = EXCLUDED.nombre_completo,
                rol = EXCLUDED.rol,
                activo = EXCLUDED.activo
            ''',
            (USERNAME, password_hash, NOMBRE_COMPLETO, ROL, True)
        )
        
        conn.commit()
        conn.close()
        
        print("✅ Usuario visualizador creado exitosamente")
        print(f"   Usuario: {USERNAME}")
        print(f"   Contraseña: {PASSWORD}")
        print(f"   Rol: {ROL}")
        print("\n📋 Permisos:")
        print("   ✓ Ver Dashboard")
        print("   ✓ Ver Datos")
        print("   ✓ Exportar CSV")
        print("   ✗ Importar Excel")
        print("   ✗ Ver Logs")
        
    except Exception as e:
        print(f"❌ Error al crear usuario: {str(e)}")
        return False
    
    return True

if __name__ == "__main__":
    crear_usuario()
