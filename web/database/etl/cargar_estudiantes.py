# cargar_estudiantes.py CORREGIDO
import pandas as pd
from sqlalchemy import create_engine
from datetime import datetime

engine = create_engine(
    "postgresql+psycopg2://postgres:123456@localhost:5432/UNITEC"
)

# LEER EXCEL
df = pd.read_excel(
    "Matriculas520820261.xlsx",
    header=None,
    skiprows=15
)

# DEBUG: Ver estructura
print("Columnas encontradas en Excel:", len(df.columns))

# ASIGNAR COLUMNAS (basado en lo que veo en tu output anterior)
df.columns = [
    "consecutivo",
    "documento",
    "nombre_estudiante",
    "codigo_programa",  # Cambié de "codigo" a "codigo_programa"
    "programa",
    "estado",
    "fecha_matricula",  # Cambié de "fecha_registro" a "fecha_matricula"
    "codigo_academico",  # Cambié de "telefono" (no es teléfono)
    "correo_personal",
    "correo_institucional",
    "categoria",
    "extra"
]

# CREAR TABLA DE ESTUDIANTES (eliminar duplicados por documento)
df_estudiantes = (
    df[
        [
            "documento",
            "nombre_estudiante",
            "correo_personal",
            "correo_institucional",
            "categoria"
        ]
    ]
    .drop_duplicates(subset=["documento"])  # Solo un registro por documento
)

# Convertir documento a string
df_estudiantes['documento'] = df_estudiantes['documento'].astype(str)

print(f"Estudiantes a cargar: {len(df_estudiantes)}")
print("\nPrimeros 5 estudiantes:")
print(df_estudiantes.head())

# CARGAR A POSTGRES (con manejo de duplicados)
try:
    # Usar to_sql con if_exists='append' y luego manejar duplicados
    df_estudiantes.to_sql(
        "estudiantes_base",
        engine,
        if_exists="append",
        index=False
    )
    
    print("\nEstudiantes cargados correctamente")
    
except Exception as e:
    print(f"Error al cargar: {e}")
    print("\nIntentando método alternativo...")
    
    # Método alternativo para evitar duplicados
    from sqlalchemy import text
    
    with engine.begin() as conn:
        for _, row in df_estudiantes.iterrows():
            conn.execute(
                text("""
                    INSERT INTO estudiantes_base 
                    (documento, nombre_estudiante, correo_personal, correo_institucional, categoria)
                    VALUES (:doc, :nombre, :email_per, :email_inst, :cat)
                    ON CONFLICT (documento) DO UPDATE SET
                    nombre_estudiante = EXCLUDED.nombre_estudiante,
                    correo_personal = EXCLUDED.correo_personal,
                    correo_institucional = EXCLUDED.correo_institucional,
                    categoria = EXCLUDED.categoria
                """),
                {
                    "doc": str(row['documento']),
                    "nombre": row['nombre_estudiante'],
                    "email_per": row['correo_personal'],
                    "email_inst": row['correo_institucional'],
                    "cat": row['categoria']
                }
            )
        print("Estudiantes cargados")