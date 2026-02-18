# INSTRUCCIONES: Cómo Ver los Cambios

## 🎯 Objetivo
Visualizar los números corregidos en el dashboard y la página de programas-detalles.

---

## 📱 Pasos para Ver los Cambios

### Opción 1: Recarga Completa del Navegador

1. **Abre el navegador** con la aplicación en ejecución
2. **Ve al Dashboard**: http://localhost:5000/
3. **Recarga la página**: 
   - Windows/Linux: `Ctrl + F5` (recarga fuerte, limpia caché)
   - macOS: `Cmd + Shift + R`

### Opción 2: Limpiar Caché y Recarga

1. **Abre Developer Tools**: `F12`
2. **Ve a la pestaña "Application"** (Chrome) o "Storage" (Firefox)
3. **Limpia el caché**:
   - Chrome: Settings → Clear site data
   - Firefox: Storage → Clear All
4. **Recarga la página**: `Ctrl + F5`

### Opción 3: Ver Directamente en Programas-Detalles

1. **Ve a**: http://localhost:5000/programas-detalles
2. **Verifica los números en la tabla**

---

## 📊 Qué Verificar

### En el Dashboard Principal

#### Tarjetas de Resumen (Arriba)
- [ ] **Total Estudiantes**: Debe mostrar 1532
- [ ] **Total Matrículas**: Debe mostrar 1614
- [ ] **Programas Activos**: Debe mostrar 39

#### Gráfico "Programas Más Solicitados" (Izquierda)
- [ ] **PSICOLOGÍA**: 297 confirmados
- [ ] **DISEÑO GRÁFICO**: 159 confirmados ← **CAMBIÓ de 157**
- [ ] **MERCADEO Y PUBLICIDAD**: 131 confirmados
- [ ] **ESPECIALIZACIÓN EN GESTIÓN DE LA SEGURIDAD**: 120 confirmados

#### Gráfico "Estados de Matrícula" (Derecha)
- [ ] **Confirmado**: 1300 (o 1301, depende de si se desglosa)
- [ ] **Por confirmar**: 299
- [ ] **Cancelado**: 14

---

## 🔍 Verificación Detallada en Programas-Detalles

### Pasos

1. **Ve a** → http://localhost:5000/programas-detalles
2. **Busca estos programas** en la tabla:

| Programa | Confirmados | Nuevos | Antiguos |
|----------|------------|--------|----------|
| PSICOLOGÍA | 297 | 34 | 263 |
| **DISEÑO GRÁFICO** | 159 | 10 | **149** |
| MERCADEO Y PUBLICIDAD | 131 | 17 | 114 |
| CINE Y TELEVISIÓN | 65 | 0 | **65** |

**Lo que cambió**:
- DISEÑO GRÁFICO antiguos: 147 → **149** (+2)
- CINE Y TELEVISIÓN antiguos: 64 → **65** (+1)

---

## 📈 Gráficos

### En Programas-Detalles

#### Gráfico Izquierda: "Top 10 Programas"
- Debe mostrarse en orden: PSICOLOGÍA (297), DISEÑO GRÁFICO (159), etc.

#### Gráfico Derecha: "Distribución Nuevos vs Antiguos"
- **Nuevos**: 254
- **Antiguos + Reintegro**: 1047
- **Suma**: 1301 ✓

---

## ✅ Validación Completa

### Checklist de Verificación

```
DASHBOARD PRINCIPAL
├─ Tarjetas de resumen
│  ├─ [ ] Total Estudiantes: 1532
│  ├─ [ ] Total Matrículas: 1614
│  └─ [ ] Programas Activos: 39
│
├─ Gráfico Programas Más Solicitados
│  ├─ [ ] #1 PSICOLOGÍA: 297
│  ├─ [ ] #2 DISEÑO GRÁFICO: 159
│  ├─ [ ] #3 MERCADEO: 131
│  └─ [ ] #4 ESPECIALIZACIÓN SEGURIDAD: 120
│
└─ Gráfico Estados
   ├─ [ ] Confirmado: 1301
   ├─ [ ] Por confirmar: 299
   └─ [ ] Cancelado: 14

PÁGINA PROGRAMAS-DETALLES
├─ Tabla de Programas
│  ├─ [ ] PSICOLOGÍA: 297 confirmados
│  ├─ [ ] DISEÑO GRÁFICO: 159 confirmados (10 nuevos + 149 antiguos)
│  ├─ [ ] CINE Y TELEVISIÓN: 65 confirmados (0 nuevos + 65 antiguos)
│  └─ [ ] Total visible en tabla
│
├─ Gráfico Top 10
│  └─ [ ] Orden correcto
│
└─ Gráfico Distribución
   ├─ [ ] Nuevos: 254
   ├─ [ ] Antiguos: 1047
   └─ [ ] Suma: 1301
```

---

## 🔧 Si No Ves los Cambios

### Posibles Causas y Soluciones

#### 1. **Caché del Navegador**
```
Solución: 
- Ctrl + Shift + Delete (abrir historial)
- Seleccionar: Cookies y datos de sitios
- Eliminar
- Recargar página
```

#### 2. **Servidor Flask aún en caché**
```
Solución:
- Detener servidor: Ctrl + C
- Esperar 5 segundos
- Reiniciar: python app.py
- Recargar navegador: Ctrl + F5
```

#### 3. **Verificar que los cambios se guardaron**
```
Solución:
- Abrir app.py en editor
- Ir a línea 226
- Verificar que diga: IN ('antiguo', 'reintegro')
```

#### 4. **Verificar BD está usando las nuevas queries**
```
python validar_conteos.py
# Debe mostrar "RESULTADO: Números coinciden perfectamente"
```

---

## 📞 Soporte

Si los números no coinciden:

1. **Ejecuta diagnóstico**:
   ```bash
   python diagnostico_conteos.py
   ```

2. **Verifica validación**:
   ```bash
   python validar_conteos.py
   ```

3. **Revisa app.py**:
   - Línea 101: `WHERE LOWER(e.nombre) = 'confirmado'`
   - Línea 121: `WHERE LOWER(e.nombre) = 'confirmado'`
   - Línea 226: `IN ('antiguo', 'reintegro')`

---

## 📝 Notas

- Los cambios se aplican **automáticamente** al recargar la página
- **No necesita reiniciar** la base de datos
- **No necesita** volver a importar Excel
- Solo recarga el navegador y verá los números correctos

---

**Fecha**: Febrero 17, 2026  
**Versión**: 1.0

