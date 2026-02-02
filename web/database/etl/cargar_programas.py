# cargar_programas.py CORREGIDO
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime

engine = create_engine(
    "postgresql+psycopg2://postgres:123456@localhost:5432/UNITEC"
)

# LEER EXCEL (misma estructura que estudiantes)
df = pd.read_excel(
    "Matriculas520820261.xlsx",
    header=None,
    skiprows=15
)

# ASIGNAR COLUMNAS
df.columns = [
    "consecutivo",
    "documento",
    "nombre_estudiante",
    "codigo_programa",
    "programa",
    "estado",
    "fecha_matricula",
    "codigo_academico",
    "correo_personal",
    "correo_institucional",
    "categoria",
    "extra"
]

# EXTRAER PROGRAMAS ÚNICOS
df_programas = (
    df[
        [
            "codigo_programa",
            "programa"
        ]
    ]
    .drop_duplicates()
    .dropna()
)

# Convertir código a string si es necesario
df_programas['codigo_programa'] = df_programas['codigo_programa'].astype(str)

print(f"Programas encontrados: {len(df_programas)}")
print("\nLista de programas:")
print(df_programas)

# CARGAR A POSTGRES
with engine.begin() as conn:
    for _, row in df_programas.iterrows():
        conn.execute(
            text("""
                INSERT INTO programas (codigo_programa, programa)
                VALUES (:codigo, :programa)
                ON CONFLICT (programa) DO UPDATE SET
                codigo_programa = EXCLUDED.codigo_programa
            """),
            {
                "codigo": row['codigo_programa'],
                "programa": row['programa']
            }
        )

print("\nProgramas cargados correctamente")