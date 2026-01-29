import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy import create_engine
from datetime import datetime

# CONEXIÓN
engine = create_engine(
    "postgresql+psycopg2://postgres:123456@localhost:5432/UNITEC"
)


# LEER EXCEL
# El encabezado REAL está en la fila 2 (index 1)
df = pd.read_excel(
    "Matriculas520820261.xlsx",
    header=15
)



# ELIMINAR COLUMNAS VACÍAS (Unnamed)
df = df.loc[:, ~df.columns.str.contains("^Unnamed")]

# NORMALIZAR NOMBRES
df.columns = (
    df.columns
    .str.lower()
    .str.strip()
    .str.replace(" ", "_")
    .str.replace("á", "a")
    .str.replace("é", "e")
    .str.replace("í", "i")
    .str.replace("ó", "o")
    .str.replace("ú", "u")
)

print("Columnas detectadas:")
print(df.columns)

df = df.dropna(how="all")


# CARGAR A POSTGRES
df.to_sql(
    "matriculas",
    engine,
    if_exists="replace",  # ahora reemplazamos estructura
    index=False
)

print("Excel importado correctamente")
input("Presiona ENTER para cerrar...")
