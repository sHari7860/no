# verificar_db.py
from sqlalchemy import create_engine, text

engine = create_engine("postgresql+psycopg2://postgres:123456@localhost:5432/UNITEC")

with engine.connect() as conn:
    print("=" * 50)
    print("VERIFICACIÓN DE BASE DE DATOS")
    print("=" * 50)
    
    # Contar registros en cada tabla
    tablas = ['estudiantes_base', 'programas', 'periodos', 'matriculas']
    
    for tabla in tablas:
        try:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar()
            print(f"✓ {tabla}: {count} registros")
        except Exception as e:
            print(f"✗ {tabla}: ERROR - {e}")
    
    print("\n" + "=" * 50)
    print("RELACIONES EN MATRÍCULAS:")
    print("=" * 50)
    
    # Verificar que las matrículas tengan relaciones válidas
    consulta = """
    SELECT 
        COUNT(*) as total,
        COUNT(CASE WHEN estudiante_id IS NOT NULL THEN 1 END) as con_estudiante,
        COUNT(CASE WHEN programa_id IS NOT NULL THEN 1 END) as con_programa,
        COUNT(CASE WHEN periodo_id IS NOT NULL THEN 1 END) as con_periodo
    FROM matriculas
    """
    
    resultado = conn.execute(text(consulta)).fetchone()
    print(f"Total matrículas: {resultado[0]}")
    print(f"Con estudiante_id: {resultado[1]}")
    print(f"Con programa_id: {resultado[2]}")
    print(f"Con periodo_id: {resultado[3]}")
    
    if resultado[0] > 0 and resultado[1] == resultado[0]:
        print("\n ¡TODAS las matrículas tienen relaciones correctas!")
    else:
        print("\n⚠️  Algunas matrículas pueden no tener relaciones completas")