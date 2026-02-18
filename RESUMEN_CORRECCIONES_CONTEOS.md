# Resumen de Correcciones de Conteos - Febrero 17, 2026

## Problema Identificado

Las cifras de estudiantes y programas no coincidían entre:
- Dashboard principal
- Página de detalles de programas
- Archivo Excel importado

Además, los números de nuevos + antiguos no sumaban el total de confirmados.

## Causa Raíz

1. **Categoría REINTEGRO no incluida**: 3 matrículas confirmadas tenían categoría REINTEGRO pero no eran contadas en el desglose de "nuevos/antiguos"
2. **Inconsistencias en case-sensitivity**: Algunas queries usaban `e.nombre = 'Confirmado'` (sensible a mayúsculas) en lugar de `LOWER(e.nombre) = 'confirmado'`
3. **Queries sin filtro de confirmado**: Algunas queries contaban TODAS las matrículas sin filtrar por estado "Confirmado"

## Soluciones Implementadas

### 1. **app.py - Ruta `/api/programas-detalles` (línea 211-244)**

**Cambio**: Se actualizo la query para incluir REINTEGRO como parte de "antiguos"

```sql
-- ANTES:
COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) = 'antiguo' THEN 1 END) AS antiguos

-- DESPUÉS:
COUNT(CASE WHEN LOWER(e.nombre) = 'confirmado' AND LOWER(c.nombre) IN ('antiguo', 'reintegro') THEN 1 END) AS antiguos
```

**Resultado**: Ahora `nuevos + antiguos = confirmados`

### 2. **app.py - Ruta `/` Dashboard (línea 125-134)**

**Cambio**: Se actualizo la query de `stats_periodo` para:
- Contar solo estudiantes CONFIRMADOS (agregar JOIN con estados_matricula)
- Usar DISTINCT m.estudiante_id para evitar duplicados
- Usar LOWER(e.nombre) para comparación case-insensitive

```sql
-- ANTES:
SELECT pr.codigo_periodo, COUNT(m.id) AS total
FROM matriculas m
JOIN periodos pr ON m.periodo_id = pr.id
GROUP BY pr.codigo_periodo

-- DESPUÉS:
SELECT pr.codigo_periodo, COUNT(DISTINCT m.estudiante_id) AS total
FROM matriculas m
JOIN periodos pr ON m.periodo_id = pr.id
JOIN estados_matricula e ON m.estado_matricula_id = e.id
WHERE LOWER(e.nombre) = 'confirmado'
GROUP BY pr.codigo_periodo
```

### 3. **app.py - Ruta `/api/estadisticas` (línea 193)**

**Cambio**: Se actualizó la query de evolución para usar la comparación case-insensitive

```sql
-- CAMBIO:
WHERE LOWER(e.nombre) = 'confirmado'
```

### 4. **app.py - Ruta `/` Dashboard (línea 118)**

**Cambio**: Se verificó y se actualizó la comparación de estado

```sql
WHERE LOWER(e.nombre) = 'confirmado'
```

## Números Validados

### Dashboard Principal
- **Total Estudiantes**: 1532 (todos sin filtro)
- **Total Matrículas**: 1614 (todas sin filtro)
- **Programas Activos**: 39 (solo con confirmados)

### Estudiantes Confirmados (DISTINCT)
- **1249 estudiantes únicos confirmados**

### Matrículas Confirmadas
- **Total**: 1301
- **Nuevos**: 254
- **Antiguos**: 1044
- **Reintegro**: 3
- **Suma**: 254 + 1047 = **1301** ✓

### Top 10 Programas
Sincronizados entre Dashboard y API programas-detalles:

| Programa | Confirmados | Nuevos | Antiguos |
|----------|------------|--------|----------|
| PSICOLOGÍA | 297 | 34 | 263 |
| DISEÑO GRÁFICO | 159 | 10 | 149 |
| MERCADEO Y PUBLICIDAD | 131 | 17 | 114 |
| ESPECIALIZACIÓN EN GESTIÓN DE LA SEGURIDAD | 120 | 56 | 64 |
| ESPECIALIZACIÓN EN GERENCIA DE PROYECTOS | 82 | 46 | 36 |
| FOTOGRAFÍA Y COMUNICACIÓN VISUAL | 68 | 0 | 68 |
| CINE Y TELEVISIÓN | 65 | 0 | 65 |
| ESPECIALIZACIÓN EN GERENCIA DEL TALENTO | 59 | 40 | 19 |
| TRABAJO EN SEMILLERO DE INVESTIGACIÓN | 31 | 0 | 31 |
| COTERMINAL MARKETING ESTRATEGICO | 30 | 0 | 30 |

## Validación

Ejecutar los scripts de validación:

```bash
python diagnostico_conteos.py    # Diagnóstico detallado
python validar_conteos.py         # Validación y comparación
```

## Archivos Modificados

1. **app.py**: 
   - Línea 118: Query top_programas con LOWER()
   - Línea 125-134: Query stats_periodo con filtro confirmado
   - Línea 193: Query evolución con LOWER()
   - Línea 211-244: Query programas-detalles con REINTEGRO

2. **Archivos de validación creados**:
   - `diagnostico_conteos.py`: Script de diagnóstico
   - `validar_conteos.py`: Script de validación final

## Cambio de Comportamiento

### Lo que cambió en números mostrados:

- **DISEÑO GRÁFICO**: Antes 147 antiguos, ahora 149 (incluye 2 REINTEGRO)
- **CINE Y TELEVISIÓN**: Antes 64 antiguos, ahora 65 (incluye 1 REINTEGRO)
- **Totales**: Ahora coinciden perfectamente

### Lo que NO cambió:

- Total confirmados sigue siendo 1301
- Total programas sigue siendo 39
- Orden de top programas sigue siendo igual
- Funcionalidad de importación NO cambió (ya tenía ON CONFLICT)

## Notas Técnicas

1. **REINTEGRO**: Estudiantes que se reintegran a un programa. Se incluyen como "antiguos" en el desglose
2. **DISTINCT m.estudiante_id**: Evita contar duplicados cuando un estudiante está en múltiples matrículas
3. **LOWER() en comparaciones**: Asegura case-insensitivity en búsquedas de estados
4. **No hay duplicados en BD**: El sistema de importación con `ON CONFLICT` funciona correctamente

