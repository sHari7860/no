# cargar_matriculas.py CORREGIDO
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
import re

# CONEXIÓN
engine = create_engine(
    "postgresql+psycopg2://postgres:123456@localhost:5432/UNITEC"
)

# LEER EXCEL
df = pd.read_excel(
    "Matriculas520820261.xlsx",
    header=None,
    skiprows=15
)

# ASIGNAR COLUMNAS (CONSISTENTE CON estudiantes.py)
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

# LIMPIEZA
df = df.dropna(subset=["documento", "programa", "estado"])
df['documento'] = df['documento'].astype(str)

print(f"Registros a procesar: {len(df)}")

# OBTENER PERIODO DEL NOMBRE DEL ARCHIVO (igual que en cargar_periodos.py)
archivo = "Matriculas520820261.xlsx"
match = re.search(r'(\d{4})', archivo)
periodo = f"{match.group(1)}-1" if match else "2026-1"

# METADATOS
df["periodo"] = periodo
df["archivo_origen"] = archivo
df["fecha_carga"] = datetime.now()

# OBTENER IDs DE TABLAS RELACIONADAS
print("\nObteniendo IDs de tablas relacionadas...")

# 1. Estudiantes
estudiantes = pd.read_sql("SELECT id, documento FROM estudiantes_base", engine)
estudiantes['documento'] = estudiantes['documento'].astype(str)
print(f"Estudiantes en DB: {len(estudiantes)}")

# 2. Programas
programas = pd.read_sql("SELECT id, programa FROM programas", engine)
print(f"Programas en DB: {len(programas)}")

# 3. Periodos
periodos = pd.read_sql(f"SELECT id, periodo FROM periodos WHERE periodo = '{periodo}'", engine)
print(f"Periodo encontrado: {len(periodos)}")

# VERIFICAR QUE EXISTAN TODOS LOS IDs
if len(periodos) == 0:
    print(f"ERROR: No se encontró el periodo '{periodo}' en la base de datos")
    print("Ejecuta primero cargar_periodos.py")
    input("ENTER para salir")
    exit()

# OBTENER IDS
periodo_id = periodos.iloc[0]['id']

# MERGE PARA OBTENER IDs
df = df.merge(estudiantes, on="documento", how="left", suffixes=('', '_est'))
df = df.merge(programas, on="programa", how="left", suffixes=('', '_prog'))

# VERIFICAR RELACIONES
sin_estudiante = df['id'].isnull().sum()
sin_programa = df['id_prog'].isnull().sum()

print(f"\nVerificación:")
print(f"  - Registros sin estudiante: {sin_estudiante}")
print(f"  - Registros sin programa: {sin_programa}")

if sin_estudiante > 0:
    print("\nDocumentos sin estudiante en DB:")
    print(df[df['id'].isnull()]['documento'].unique()[:10])
    
if sin_programa > 0:
    print("\nProgramas sin referencia en DB:")
    print(df[df['id_prog'].isnull()]['programa'].unique())

# FILTRAR SOLO REGISTROS COMPLETOS
df_completo = df[~df['id'].isnull() & ~df['id_prog'].isnull()].copy()
print(f"\nRegistros completos para insertar: {len(df_completo)}")

if len(df_completo) == 0:
    print("ERROR: No hay registros completos para insertar")
    input("ENTER para salir")
    exit()

# PREPARAR DATA FINAL
df_final = df_completo.rename(columns={
    'id': 'estudiante_id',
    'id_prog': 'programa_id'
})

df_final['periodo_id'] = periodo_id

# COLUMNAS PARA MATRÍCULAS
df_matriculas = df_final[[
    'estudiante_id',
    'programa_id',
    'periodo_id',
    'estado',
    'fecha_matricula',
    'fecha_carga',
    'archivo_origen'
]]

# INSERTAR EN BASE DE DATOS (evitar duplicados)
try:
    # Usar SQL explícito para manejar conflictos
    with engine.begin() as conn:
        for _, row in df_matriculas.iterrows():
            conn.execute(
                text("""
                    INSERT INTO matriculas 
                    (estudiante_id, programa_id, periodo_id, estado, fecha_matricula, fecha_carga, archivo_origen)
                    VALUES (:est_id, :prog_id, :per_id, :estado, :fecha_mat, :fecha_carga, :archivo)
                    ON CONFLICT (estudiante_id, programa_id, periodo_id) DO UPDATE SET
                    estado = EXCLUDED.estado,
                    fecha_matricula = EXCLUDED.fecha_matricula,
                    fecha_carga = EXCLUDED.fecha_carga
                """),
                {
                    "est_id": int(row['estudiante_id']),
                    "prog_id": int(row['programa_id']),
                    "per_id": int(row['periodo_id']),
                    "estado": row['estado'],
                    "fecha_mat": row['fecha_matricula'],
                    "fecha_carga": row['fecha_carga'],
                    "archivo": row['archivo_origen']
                }
            )
    
    print(f"\n¡ÉXITO! Se procesaron {len(df_matriculas)} matrículas")
    
    # VERIFICAR
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM matriculas")).scalar()
        print(f"Total de matrículas en la base de datos: {total}")
        
except Exception as e:
    print(f"\nError al insertar: {e}")

print("\nProceso completado!")
input("ENTER para salir")