"""
Reporte de cambios en conteos - Antes vs Después
"""
from database import get_db_connection

def generar_reporte():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*100)
    print("REPORTE: CAMBIOS EN CONTEOS - ANTES vs DESPUÉS")
    print("="*100)
    
    # Obtener datos actuales
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
        LIMIT 15
    ''')
    programas = cursor.fetchall()
    
    # Datos antiguos (sin REINTEGRO)
    datos_antes = {
        'PSICOLOGÍA': {'confirmados': 297, 'nuevos': 34, 'antiguos': 263},
        'DISEÑO GRÁFICO': {'confirmados': 159, 'nuevos': 10, 'antiguos': 147},
        'MERCADEO Y PUBLICIDAD': {'confirmados': 131, 'nuevos': 17, 'antiguos': 114},
        'ESPECIALIZACIÓN EN GESTIÓN DE LA SEGURIDAD': {'confirmados': 120, 'nuevos': 56, 'antiguos': 64},
        'ESPECIALIZACIÓN EN GERENCIA DE PROYECTOS': {'confirmados': 82, 'nuevos': 46, 'antiguos': 36},
        'FOTOGRAFÍA Y COMUNICACIÓN VISUAL': {'confirmados': 68, 'nuevos': 0, 'antiguos': 68},
        'CINE Y TELEVISIÓN': {'confirmados': 65, 'nuevos': 0, 'antiguos': 64},
        'ESPECIALIZACIÓN EN GERENCIA DEL TALENTO': {'confirmados': 59, 'nuevos': 40, 'antiguos': 19},
    }
    
    print("\nCOMPARACIÓN ANTES vs DESPUÉS (PRIMEROS 15 PROGRAMAS):\n")
    print(f"{'Programa':<40} | {'Antes':<25} | {'Ahora':<25} | {'Cambio':<10}")
    print("-" * 120)
    
    cambios_detectados = []
    
    for prog, conf, nuevos, antiguos in programas:
        prog_key = prog.strip()
        
        # Buscar datos anteriores
        datos_ant = None
        for key in datos_antes.keys():
            if key.lower() in prog_key.lower() or prog_key.lower() in key.lower():
                datos_ant = datos_antes[key]
                break
        
        if datos_ant:
            ant_antiguos = datos_ant['antiguos']
            ant_nuevos = datos_ant['nuevos']
            ant_conf = datos_ant['confirmados']
            
            cambio_antiguos = antiguos - ant_antiguos
            cambio_nuevos = nuevos - ant_nuevos
            
            before_str = f"N:{ant_nuevos:<3} A:{ant_antiguos:<3} C:{ant_conf:<3}"
            after_str = f"N:{nuevos:<3} A:{antiguos:<3} C:{conf:<3}"
            
            if cambio_antiguos != 0 or cambio_nuevos != 0:
                cambio_str = f"N:{cambio_nuevos:+d} A:{cambio_antiguos:+d}"
                print(f"{prog[:40]:<40} | {before_str:<25} | {after_str:<25} | {cambio_str:<10}")
                cambios_detectados.append({
                    'programa': prog,
                    'antes_antiguos': ant_antiguos,
                    'ahora_antiguos': antiguos,
                    'cambio': cambio_antiguos
                })
            else:
                print(f"{prog[:40]:<40} | {before_str:<25} | {after_str:<25} | {'Sin cambio':<10}")
    
    # Resumen
    print("\n" + "="*100)
    print("RESUMEN DE CAMBIOS DETECTADOS")
    print("="*100)
    
    if cambios_detectados:
        print(f"\nSe detectaron {len(cambios_detectados)} programas con cambios en antiguos/nuevos:\n")
        for item in cambios_detectados:
            print(f"  {item['programa'][:50]:<50}")
            print(f"    Antiguos: {item['antes_antiguos']} -> {item['ahora_antiguos']} (diferencia: {item['cambio']:+d})")
    else:
        print("\nNo se detectaron cambios (datos ya estaban correctos)")
    
    # Validación total
    print("\n" + "="*100)
    print("VALIDACIÓN FINAL DE TOTALES")
    print("="*100)
    
    cursor.execute('''
        SELECT 
            COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' THEN 1 END) AS confirmados,
            COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'nuevo' THEN 1 END) AS nuevos,
            COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) IN ('antiguo', 'reintegro') THEN 1 END) AS antiguos,
            COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'reintegro' THEN 1 END) AS reintegro
        FROM matriculas m
        LEFT JOIN categorias c ON m.categoria_id = c.id
        LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
    ''')
    
    conf, nuevos, antiguos, reintegro = cursor.fetchone()
    
    print(f"\nTotal de Matrículas Confirmadas: {conf}")
    print(f"  - Nuevos: {nuevos}")
    print(f"  - Antiguos: {antiguos - reintegro}")
    print(f"  - Reintegro: {reintegro}")
    print(f"  - Suma: {nuevos} + {antiguos - reintegro} + {reintegro} = {nuevos + antiguos}")
    
    if (nuevos + antiguos) == conf:
        print(f"\n✓ VALIDACIÓN EXITOSA: Los números coinciden perfectamente")
    else:
        print(f"\n✗ VALIDACIÓN FALLIDA: Discrepancia de {conf - (nuevos + antiguos)}")
    
    conn.close()

if __name__ == '__main__':
    generar_reporte()
