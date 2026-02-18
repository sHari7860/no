"""
Script de diagnóstico para verificar la exactitud de los conteos
"""
from database import get_db_connection
import pandas as pd

def diagnostico():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    print("="*80)
    print("DIAGNÓSTICO DE CONTEOS - MATRÍCULAS")
    print("="*80)
    
    # 1. Conteo básico de estudiantes (sin filtrar)
    print("\n1. ESTUDIANTES TOTALES (sin filtrar)")
    cursor.execute('SELECT COUNT(*) FROM estudiantes')
    total_est = cursor.fetchone()[0]
    print(f"   Total estudiantes en BD: {total_est}")
    
    # 2. Conteo de estudiantes CON matrículas confirmadas
    print("\n2. ESTUDIANTES CON MATRÍCULAS CONFIRMADAS (DISTINCT)")
    cursor.execute('''
        SELECT COUNT(DISTINCT m.estudiante_id)
        FROM matriculas m
        JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE LOWER(e.nombre) = 'confirmado'
    ''')
    est_confirmados = cursor.fetchone()[0]
    print(f"   Estudiantes únicos confirmados: {est_confirmados}")
    
    # 3. Total de matrículas (sin filtrar)
    print("\n3. MATRÍCULAS TOTALES (sin filtrar)")
    cursor.execute('SELECT COUNT(*) FROM matriculas')
    total_mat = cursor.fetchone()[0]
    print(f"   Total matrículas en BD: {total_mat}")
    
    # 4. Total de matrículas confirmadas
    print("\n4. MATRÍCULAS CONFIRMADAS")
    cursor.execute('''
        SELECT COUNT(m.id)
        FROM matriculas m
        JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE LOWER(e.nombre) = 'confirmado'
    ''')
    mat_confirmadas = cursor.fetchone()[0]
    print(f"   Matrículas confirmadas: {mat_confirmadas}")
    
    # 5. Desglose de matrículas por estado
    print("\n5. DESGLOSE DE MATRÍCULAS POR ESTADO")
    cursor.execute('''
        SELECT e.nombre, COUNT(m.id)
        FROM matriculas m
        JOIN estados_matricula e ON m.estado_matricula_id = e.id
        GROUP BY e.nombre
        ORDER BY COUNT(m.id) DESC
    ''')
    for row in cursor.fetchall():
        print(f"   {row[0]}: {row[1]}")
    
    # 6. Conteo de programas (con confirmados)
    print("\n6. PROGRAMAS CON CONFIRMADOS")
    cursor.execute('''
        SELECT COUNT(DISTINCT p.id)
        FROM programas p
        LEFT JOIN matriculas m ON p.id = m.programa_id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE LOWER(e.nombre) = 'confirmado'
    ''')
    programas_confirmados = cursor.fetchone()[0]
    print(f"   Programas con confirmados: {programas_confirmados}")
    
    # 7. Top programas con sus conteos
    print("\n7. TOP 15 PROGRAMAS - DESGLOSE CONFIRMADOS")
    print("   (Nombre | Confirmados | Nuevos | Antiguos | Total)")
    cursor.execute('''
        SELECT p.nombre_original, 
               COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' THEN 1 END) AS confirmados,
               COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'nuevo' THEN 1 END) AS nuevos,
               COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'antiguo' THEN 1 END) AS antiguos,
               COUNT(m.id) AS total_matrículas
        FROM programas p
        LEFT JOIN matriculas m ON p.id = m.programa_id
        LEFT JOIN categorias c ON m.categoria_id = c.id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE p.nombre_original IS NOT NULL
        GROUP BY p.id, p.nombre_original
        HAVING COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' THEN 1 END) > 0
        ORDER BY confirmados DESC
        LIMIT 15
    ''')
    for row in cursor.fetchall():
        print(f"   {row[0][:40]:<40} | {row[1]:>3} | {row[2]:>5} | {row[3]:>7} | {row[4]:>5}")
    
    # 8. Verificar duplicados en matriculas
    print("\n8. VERIFICAR DUPLICADOS EN MATRÍCULAS")
    cursor.execute('''
        SELECT periodo_id, estudiante_id, programa_id, COUNT(*)
        FROM matriculas
        GROUP BY periodo_id, estudiante_id, programa_id
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC
        LIMIT 5
    ''')
    duplicados = cursor.fetchall()
    if duplicados:
        print(f"   ** Se encontraron {len(duplicados)} grupos duplicados:")
        for row in duplicados:
            print(f"      Período: {row[0]}, Estudiante: {row[1]}, Programa: {row[2]} - Count: {row[3]}")
    else:
        print("   * No hay duplicados detectados")
    
    # 9. Verificar categoría NUEVO vs ANTIGUO
    print("\n9. DESGLOSE DE CATEGORÍAS")
    cursor.execute('''
        SELECT c.nombre, COUNT(m.id)
        FROM matriculas m
        JOIN categorias c ON m.categoria_id = c.id
        GROUP BY c.nombre
        ORDER BY COUNT(m.id) DESC
    ''')
    for row in cursor.fetchall():
        print(f"   {row[0]}: {row[1]}")
    
    # 10. Suma manual de nuevos + antiguos + reintegro vs confirmados
    print("\n10. VALIDACIÓN: NUEVOS + ANTIGUOS + REINTEGRO = CONFIRMADOS?")
    cursor.execute('''
        SELECT 
            COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'nuevo' THEN 1 END) AS nuevos,
            COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'antiguo' THEN 1 END) AS antiguos,
            COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'reintegro' THEN 1 END) AS reintegros,
            COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' THEN 1 END) AS confirmados
        FROM matriculas m
        LEFT JOIN categorias c ON m.categoria_id = c.id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
    ''')
    row = cursor.fetchone()
    nuevos = row[0]
    antiguos = row[1]
    reintegros = row[2]
    confirmados = row[3]
    suma = nuevos + antiguos + reintegros
    print(f"   Nuevos: {nuevos}")
    print(f"   Antiguos: {antiguos}")
    print(f"   Reintegros: {reintegros}")
    print(f"   Suma (Nuevos + Antiguos + Reintegros): {suma}")
    print(f"   Total Confirmados: {confirmados}")
    if suma == confirmados:
        print("   * Los números coinciden perfectamente")
    else:
        print(f"   ** DISCREPANCIA: Suma ({suma}) != Confirmados ({confirmados})")
        print(f"   Diferencia: {confirmados - suma}")
    
    conn.close()

if __name__ == '__main__':
    diagnostico()
