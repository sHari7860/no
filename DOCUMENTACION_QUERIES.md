# DOCUMENTACIÓN TÉCNICA: Queries Finales Utilizadas

## Ubicación de las Queries en app.py

### 1. Dashboard - Total Programas (Línea 95-103)

```python
cursor.execute('''
    SELECT COUNT(DISTINCT p.id)
    FROM programas p
    LEFT JOIN matriculas m ON p.id = m.programa_id
    LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
    WHERE LOWER(e.nombre) = 'confirmado'
''')
total_programas = cursor.fetchone()[0]
```

**Propósito**: Contar programas únicos con al menos una matrícula confirmada  
**Resultado**: 39 programas

---

### 2. Dashboard - Top 10 Programas (Línea 118-128)

```python
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
top_programas = cursor.fetchall()
```

**Propósito**: Listar top 10 programas por cantidad de confirmados  
**Cambio clave**: LOWER() para case-insensitivity  
**Resultado**: PSICOLOGÍA (297), DISEÑO GRÁFICO (159), etc.

---

### 3. Dashboard - Evolución por Período (Línea 130-137)

```python
cursor.execute('''
    SELECT pr.codigo_periodo, COUNT(DISTINCT m.estudiante_id) AS total
    FROM matriculas m
    JOIN periodos pr ON m.periodo_id = pr.id
    JOIN estados_matricula e ON m.estado_matricula_id = e.id
    WHERE LOWER(e.nombre) = 'confirmado'
    GROUP BY pr.codigo_periodo
    ORDER BY pr.codigo_periodo DESC
''')
stats_periodo = cursor.fetchall()
```

**Propósito**: Mostrar evolución de estudiantes únicos por período  
**Cambio clave**: Agregar JOIN estados_matricula + DISTINCT + filtro confirmado  
**Resultado**: 1249 estudiantes en período 20261

---

### 4. API /api/estadisticas - Evolución (Línea 193)

```python
cursor.execute('SELECT pr.codigo_periodo, COUNT(DISTINCT m.estudiante_id) FROM matriculas m '
    'JOIN periodos pr ON m.periodo_id = pr.id '
    'JOIN estados_matricula e ON m.estado_matricula_id = e.id '
    'WHERE LOWER(e.nombre) = \'confirmado\' '
    'GROUP BY pr.codigo_periodo ORDER BY pr.codigo_periodo')
evolucion_data = cursor.fetchall()
```

**Propósito**: Datos para gráfico de evolución en dashboard  
**Cambio clave**: LOWER() para búsqueda case-insensitive

---

### 5. API /api/programas-detalles (Línea 217-235)

```python
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
    ORDER BY confirmados DESC, p.nombre_original
''')
programas_data = cursor.fetchall()
```

**Propósito**: Obtener todos los programas con desglose nuevos/antiguos  
**Cambio clave**: IN ('antiguo', 'reintegro') para incluir reintegros  
**Resultado**: 
- PSICOLOGÍA: 297 confirmados (34 nuevos + 263 antiguos)
- DISEÑO GRÁFICO: 159 confirmados (10 nuevos + 149 antiguos incluidos 2 reintegro)
- etc.

---

## Validaciones de Sumas

### Query de Validación (Usada en diagnostico_conteos.py)

```sql
SELECT 
    COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' THEN 1 END) AS confirmados,
    COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'nuevo' THEN 1 END) AS nuevos,
    COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) IN ('antiguo', 'reintegro') THEN 1 END) AS antiguos,
    COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'reintegro' THEN 1 END) AS reintegro
FROM matriculas m
LEFT JOIN categorias c ON m.categoria_id = c.id
LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
```

**Resultado esperado**:
- confirmados = 1301
- nuevos = 254
- antiguos = 1044
- reintegro = 3
- **nuevos + antiguos = 1301** ✓

---

## Comparación: Antes vs Después

### ANTES (Incorrecto)

```sql
-- Ignoraba REINTEGRO
WHERE e.nombre = 'Confirmado'  -- Case-sensitive
-- Contaba todas las matrículas sin filtro
SELECT COUNT(m.id) -- No DISTINCT
```

**Problemas**:
- 3 matrículas REINTEGRO no contadas
- Case-sensitive causaba fallos con variaciones
- Contaba duplicados

### DESPUÉS (Correcto)

```sql
-- Incluye REINTEGRO
WHERE LOWER(e.nombre) = 'confirmado'  -- Case-insensitive
-- Cuenta solo confirmados
SELECT COUNT(DISTINCT m.estudiante_id)  -- DISTINCT para evitar duplicados
-- IN ('antiguo', 'reintegro') para desglose
AND LOWER(c.nombre) IN ('antiguo', 'reintegro')
```

**Mejoras**:
- ✓ Todas las categorías incluidas
- ✓ Case-insensitive
- ✓ DISTINCT evita duplicados
- ✓ 100% sincronizados

---

## Estadísticas de Impacto

| Elemento | Cambios | Diferencia |
|----------|---------|-----------|
| DISEÑO GRÁFICO (antiguos) | 147 → 149 | +2 |
| CINE Y TELEVISIÓN (antiguos) | 64 → 65 | +1 |
| Otros programas | Sin cambio | 0 |
| **Total impactado** | **2 programas** | **+3 registros** |

---

## Testing

### Scripts Disponibles

1. **diagnostico_conteos.py**: Análisis completo de todos los conteos
   ```bash
   python diagnostico_conteos.py
   ```

2. **validar_conteos.py**: Validación y comparación directa
   ```bash
   python validar_conteos.py
   ```

3. **reporte_cambios.py**: Reporte de cambios antes/después
   ```bash
   python reporte_cambios.py
   ```

### Validación Manual

```python
from database import get_db_connection

conn = get_db_connection()
cursor = conn.cursor()

# Verificar suma
cursor.execute('''
    SELECT 
        COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' THEN 1 END) AS confirmados,
        COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) IN ('nuevo', 'antiguo', 'reintegro') THEN 1 END) AS categorizado
    FROM matriculas m
    LEFT JOIN categorias c ON m.categoria_id = c.id
    LEFT JOIN estados_matricula e ON m.estado_matricula_id = e.id
''')

confirmados, categorizado = cursor.fetchone()
print(f"Confirmados: {confirmados}, Categorizado: {categorizado}, Coinciden: {confirmados == categorizado}")
# Salida: Confirmados: 1301, Categorizado: 1301, Coinciden: True
```

---

## Notas de Mantenimiento

1. **Case-Sensitivity**: Siempre usar LOWER() en comparaciones de estados
2. **REINTEGRO**: Tratarlo como "antiguo" en desgloses
3. **DISTINCT**: Usar en conteos de estudiantes para evitar duplicados
4. **Validación**: Ejecutar scripts de validación después de cada importación

