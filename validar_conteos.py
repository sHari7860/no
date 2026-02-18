"""
Script de validación final de conteos
Verifica que todas las queries sean consistentes
"""
from database import get_db_connection

def validar_conteos():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    print("="*80)
    print("VALIDACIÓN FINAL DE CONTEOS")
    print("="*80)
    
    # 1. Dashboard - Total Estudiantes
    cursor.execute('SELECT COUNT(*) FROM estudiantes')
    total_est_todos = cursor.fetchone()[0]
    
    # 2. Dashboard - Matrículas
    cursor.execute('SELECT COUNT(*) FROM matriculas')
    total_mat_todos = cursor.fetchone()[0]
    
    # 3. Dashboard - Programas con confirmados
    cursor.execute('''
        SELECT COUNT(DISTINCT p.id)
        FROM programas p
        LEFT JOIN matriculas m ON p.id = m.programa_id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE LOWER(e.nombre) = 'confirmado'
    ''')
    total_programas = cursor.fetchone()[0]
    
    # 4. Top 10 programas confirmados (para dashboard)
    cursor.execute('''
        SELECT p.nombre_original, COUNT(m.id) AS total
        FROM matriculas m
        JOIN programas p ON m.programa_id = p.id
        JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE LOWER(e.nombre) = 'confirmado'
        GROUP BY p.nombre_original
        ORDER BY total DESC
        LIMIT 10
    ''')
    top10_dash = cursor.fetchall()
    
    # 5. Evolución por período (dashboard - estudiantes únicos confirmados)
    cursor.execute('''
        SELECT pr.codigo_periodo, COUNT(DISTINCT m.estudiante_id) AS total
        FROM matriculas m
        JOIN periodos pr ON m.periodo_id = pr.id
        JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE LOWER(e.nombre) = 'confirmado'
        GROUP BY pr.codigo_periodo
        ORDER BY pr.codigo_periodo DESC
    ''')
    evolucion_dash = cursor.fetchall()
    
    # 6. Programas detalle API (con nuevos/antiguos)
    cursor.execute('''
        SELECT p.nombre_original, 
               COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' THEN 1 END) AS confirmados,
               COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'nuevo' THEN 1 END) AS nuevos,
               COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) IN ('antiguo', 'reintegro') THEN 1 END) AS antiguos
        FROM programas p
        LEFT JOIN matriculas m ON p.id = m.programa_id
        LEFT JOIN categorias c ON m.categoria_id = c.id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
        WHERE p.nombre_original IS NOT NULL
        GROUP BY p.nombre_original
        ORDER BY confirmados DESC
        LIMIT 10
    ''')
    programas_api = cursor.fetchall()
    
    print("\n1. DASHBOARD CARDS")
    print(f"   Total Estudiantes (sin filtro): {total_est_todos}")
    print(f"   Total Matrículas (sin filtro): {total_mat_todos}")
    print(f"   Programas Activos (con confirmados): {total_programas}")
    
    print("\n2. TOP 10 PROGRAMAS (Dashboard)")
    print("   Programa | Confirmados")
    for prog, total in top10_dash:
        print(f"   {prog[:40]:<40} | {total:>4}")
    
    print("\n3. EVOLUCIÓN POR PERÍODO (Dashboard - Estudiantes únicos)")
    print("   Período | Estudiantes")
    for periodo, total in evolucion_dash:
        print(f"   {str(periodo):<8} | {total:>4}")
    
    print("\n4. TOP 10 PROGRAMAS (API programas-detalles)")
    print("   Programa | Confirmados | Nuevos | Antiguos")
    for prog, conf, nuevos, antiguos in programas_api:
        print(f"   {prog[:30]:<30} | {conf:>3} | {nuevos:>5} | {antiguos:>7}")
    
    # 7. Validación de sumas
    print("\n5. VALIDACIÓN DE SUMAS")
    cursor.execute('''
        SELECT 
            COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' THEN 1 END) AS confirmados,
            COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'nuevo' THEN 1 END) AS nuevos,
            COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) IN ('antiguo', 'reintegro') THEN 1 END) AS antiguos
        FROM matriculas m
        LEFT JOIN categorias c ON m.categoria_id = c.id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
    ''')
    conf, nuevos, antiguos = cursor.fetchone()
    suma = nuevos + antiguos
    print(f"   Nuevos: {nuevos}")
    print(f"   Antiguos + Reintegro: {antiguos}")
    print(f"   Suma: {suma}")
    print(f"   Total Confirmados: {conf}")
    if suma == conf:
        print("   ** RESULTADO: Números coinciden perfectamente **")
    else:
        print(f"   ** RESULTADO: Discrepancia de {conf - suma} **")
    
    # 8. Comparación Top 10 entre sources
    print("\n6. COMPARACIÓN TOP 10 PROGRAMAS")
    print("   Dashboard vs API debe ser idéntico")
    
    top10_dash_dict = {prog: total for prog, total in top10_dash}
    for prog, conf, nuevos, antiguos in programas_api:
        dash_valor = top10_dash_dict.get(prog, "NO ENCONTRADO")
        if conf == dash_valor:
            print(f"   {prog[:35]:<35} - API: {conf:>3}, Dashboard: {dash_valor:>3} ** OK **")
        else:
            print(f"   {prog[:35]:<35} - API: {conf:>3}, Dashboard: {dash_valor:>3} ** MISMATCH **")
    
    conn.close()

if __name__ == '__main__':
    validar_conteos()
