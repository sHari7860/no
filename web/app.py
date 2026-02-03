from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
from utils.file_processor import procesar_excel_completo
from flask import Flask, render_template, url_for

app = Flask(__name__, 
            static_folder='WEB/static',  # Ruta a la carpeta static
            template_folder='WEB/templates')
app.config['SECRET_KEY'] = 'tu-clave-secreta'

app = Flask(__name__)
app.secret_key = 'unitec_secret_key_2026'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Crear carpeta uploads si no existe
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.route('/')
def index():
    """Dashboard principal"""
    try:
        from database.connection import engine
        from sqlalchemy import text
        
        with engine.connect() as conn:
            # Estadísticas generales
            stats = {
                'estudiantes': conn.execute(text("SELECT COUNT(*) FROM estudiantes_base")).scalar() or 0,
                'programas': conn.execute(text("SELECT COUNT(*) FROM programas")).scalar() or 0,
                'matriculas': conn.execute(text("SELECT COUNT(*) FROM matriculas")).scalar() or 0,
                'periodos': conn.execute(text("SELECT COUNT(*) FROM periodos")).scalar() or 0,
            }
            
            # Matrículas por programa
            por_programa = conn.execute(text("""
                SELECT p.programa, COUNT(*) as cantidad
                FROM matriculas m
                JOIN programas p ON m.programa_id = p.id
                GROUP BY p.programa
                ORDER BY cantidad DESC LIMIT 10
            """)).fetchall()
            
            # Distribución por estado
            por_estado = conn.execute(text("""
                SELECT estado, COUNT(*) as cantidad
                FROM matriculas
                WHERE estado IS NOT NULL
                GROUP BY estado
                ORDER BY cantidad DESC
            """)).fetchall()
            
            # Matrículas por periodo
            por_periodo = conn.execute(text("""
                SELECT pr.periodo, COUNT(*) as cantidad
                FROM matriculas m
                JOIN periodos pr ON m.periodo_id = pr.id
                GROUP BY pr.periodo
                ORDER BY pr.periodo DESC
            """)).fetchall()
            
            # Últimos archivos cargados
            archivos = conn.execute(text("""
                SELECT DISTINCT archivo_origen, MAX(fecha_carga) as ultima_carga
                FROM matriculas 
                WHERE archivo_origen IS NOT NULL
                GROUP BY archivo_origen
                ORDER BY ultima_carga DESC LIMIT 5
            """)).fetchall()
            
        return render_template('index.html', 
                             stats=stats, 
                             por_programa=por_programa,
                             por_estado=por_estado,
                             por_periodo=por_periodo,
                             archivos=archivos)
        
    except Exception as e:
        print(f"Error al cargar datos: {e}")
        flash(f"Error al cargar datos: {str(e)}", "error")
        return render_template('index.html', 
                             stats={}, 
                             por_programa=[], 
                             por_estado=[], 
                             por_periodo=[], 
                             archivos=[])

@app.route('/estudiantes')
def estudiantes_dashboard():
    """Dashboard detallado de estudiantes"""
    try:
        from database.connection import engine
        from sqlalchemy import text
        
        with engine.connect() as conn:
            # 1. Total estudiantes
            total_estudiantes = conn.execute(
                text("SELECT COUNT(*) FROM estudiantes_base")
            ).scalar() or 0
            
            # 2. Estudiantes confirmados (con al menos una matrícula confirmada)
            estudiantes_confirmados = conn.execute(text("""
                SELECT COUNT(DISTINCT e.id)
                FROM estudiantes_base e
                JOIN matriculas m ON e.id = m.estudiante_id
                WHERE m.estado = 'Confirmado'
            """)).scalar() or 0
            
            # 3. Estudiantes por confirmar
            estudiantes_por_confirmar = conn.execute(text("""
                SELECT COUNT(DISTINCT e.id)
                FROM estudiantes_base e
                JOIN matriculas m ON e.id = m.estudiante_id
                WHERE m.estado = 'Por confirmar'
            """)).scalar() or 0
            
            # 4. Estudiantes nuevos vs antiguos (por categoría)
            estudiantes_categoria = conn.execute(text("""
                SELECT categoria, COUNT(*) as cantidad
                FROM estudiantes_base
                WHERE categoria IS NOT NULL
                GROUP BY categoria
                ORDER BY cantidad DESC
            """)).fetchall()
            
            # 5. Distribución por programa (top 10)
            estudiantes_por_programa = conn.execute(text("""
                SELECT p.programa, COUNT(DISTINCT e.id) as cantidad
                FROM estudiantes_base e
                JOIN matriculas m ON e.id = m.estudiante_id
                JOIN programas p ON m.programa_id = p.id
                GROUP BY p.programa
                ORDER BY cantidad DESC
                LIMIT 10
            """)).fetchall()
            
            # 6. Estudiantes sin matrícula
            estudiantes_sin_matricula = conn.execute(text("""
                SELECT COUNT(*)
                FROM estudiantes_base e
                LEFT JOIN matriculas m ON e.id = m.estudiante_id
                WHERE m.id IS NULL
            """)).scalar() or 0
            
            # 7. Estudiantes con múltiples programas
            estudiantes_multiple_programa = conn.execute(text("""
                SELECT COUNT(*)
                FROM (
                    SELECT e.id, COUNT(DISTINCT m.programa_id) as num_programas
                    FROM estudiantes_base e
                    JOIN matriculas m ON e.id = m.estudiante_id
                    GROUP BY e.id
                    HAVING COUNT(DISTINCT m.programa_id) > 1
                ) AS subquery
            """)).scalar() or 0
            
            # 8. Tendencias mensuales (nuevos estudiantes por mes)
            nuevos_por_mes = conn.execute(text("""
                SELECT 
                    TO_CHAR(fecha_creacion, 'YYYY-MM') as mes,
                    COUNT(*) as nuevos_estudiantes
                FROM estudiantes_base
                WHERE fecha_creacion >= CURRENT_DATE - INTERVAL '6 months'
                GROUP BY TO_CHAR(fecha_creacion, 'YYYY-MM')
                ORDER BY mes
            """)).fetchall()
            
        # Preparar datos para gráficos
        categorias_labels = [cat[0] for cat in estudiantes_categoria]
        categorias_data = [cat[1] for cat in estudiantes_categoria]
        
        programas_labels = [prog[0][:20] + ('...' if len(prog[0]) > 20 else '') for prog in estudiantes_por_programa]
        programas_data = [prog[1] for prog in estudiantes_por_programa]
        
        meses_labels = [mes[0] for mes in nuevos_por_mes]
        meses_data = [mes[1] for mes in nuevos_por_mes]
        
        return render_template('estudiantes.html',
                             total_estudiantes=total_estudiantes,
                             estudiantes_confirmados=estudiantes_confirmados,
                             estudiantes_por_confirmar=estudiantes_por_confirmar,
                             estudiantes_categoria=estudiantes_categoria,
                             estudiantes_por_programa=estudiantes_por_programa,
                             estudiantes_sin_matricula=estudiantes_sin_matricula,
                             estudiantes_multiple_programa=estudiantes_multiple_programa,
                             nuevos_por_mes=nuevos_por_mes,
                             categorias_labels=categorias_labels,
                             categorias_data=categorias_data,
                             programas_labels=programas_labels,
                             programas_data=programas_data,
                             meses_labels=meses_labels,
                             meses_data=meses_data)
        
    except Exception as e:
        print(f"Error en dashboard estudiantes: {e}")
        flash(f"Error cargando datos de estudiantes: {str(e)}", "error")
        return render_template('estudiantes.html',
                             total_estudiantes=0,
                             estudiantes_confirmados=0,
                             estudiantes_por_confirmar=0,
                             estudiantes_categoria=[],
                             estudiantes_por_programa=[],
                             estudiantes_sin_matricula=0,
                             estudiantes_multiple_programa=0,
                             nuevos_por_mes=[],
                             categorias_labels=[],
                             categorias_data=[],
                             programas_labels=[],
                             programas_data=[],
                             meses_labels=[],
                             meses_data=[])

@app.route('/reports')
def reports():
    """Página de reportes avanzados"""
    try:
        from database.connection import engine
        from sqlalchemy import text
        
        with engine.connect() as conn:
            # Reporte 1: Matrículas por periodo
            por_periodo = conn.execute(text("""
                SELECT pr.periodo, COUNT(*) as cantidad
                FROM matriculas m
                JOIN periodos pr ON m.periodo_id = pr.id
                GROUP BY pr.periodo
                ORDER BY pr.periodo DESC
            """)).fetchall()
            
            # Reporte 2: Estado de matrículas
            por_estado = conn.execute(text("""
                SELECT estado, COUNT(*) as cantidad
                FROM matriculas
                GROUP BY estado
                ORDER BY cantidad DESC
            """)).fetchall()
            
            # Reporte 3: Top programas
            top_programas = conn.execute(text("""
                SELECT p.programa, COUNT(*) as matriculados
                FROM matriculas m
                JOIN programas p ON m.programa_id = p.id
                GROUP BY p.programa
                ORDER BY matriculados DESC
                LIMIT 15
            """)).fetchall()
            
        return render_template('reports.html',
                             por_periodo=por_periodo,
                             por_estado=por_estado,
                             top_programas=top_programas)
        
    except Exception as e:
        flash(f"Error generando reportes: {str(e)}", "error")
        return render_template('reports.html',
                             por_periodo=[],
                             por_estado=[],
                             top_programas=[])

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    """Subir y procesar archivo Excel"""
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No se seleccionó archivo', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        
        if file.filename == '':
            flash('No se seleccionó archivo', 'error')
            return redirect(request.url)
        
        if file and file.filename.endswith('.xlsx'):
            try:
                # Guardar archivo
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
                file.save(filepath)
                
                # Procesar archivo
                resultados = procesar_excel_completo(filepath, file.filename)
                
                # Mostrar resultados
                for tabla, success, msg in resultados:
                    if success:
                        flash(f"{tabla}: {msg}", 'success')
                    else:
                        flash(f"{tabla}: ERROR - {msg}", 'error')
                
                # Limpiar
                os.remove(filepath)
                
                return redirect(url_for('index'))
                
            except Exception as e:
                flash(f'Error: {str(e)}', 'error')
        else:
            flash('Solo archivos Excel (.xlsx)', 'error')
    
    return render_template('upload.html')

@app.route('/api/estudiantes/graficos')
def api_estudiantes_graficos():
    """API para datos de gráficos de estudiantes"""
    try:
        from database.connection import engine
        from sqlalchemy import text
        
        with engine.connect() as conn:
            # Datos para gráfico de categorías
            categorias = conn.execute(text("""
                SELECT categoria, COUNT(*) as cantidad
                FROM estudiantes_base
                WHERE categoria IS NOT NULL
                GROUP BY categoria
            """)).fetchall()
            
            # Datos para gráfico de estado
            estados = conn.execute(text("""
                SELECT 
                    CASE 
                        WHEN EXISTS (
                            SELECT 1 FROM matriculas m 
                            WHERE m.estudiante_id = e.id AND m.estado = 'Confirmado'
                        ) THEN 'Confirmado'
                        WHEN EXISTS (
                            SELECT 1 FROM matriculas m 
                            WHERE m.estudiante_id = e.id AND m.estado = 'Por confirmar'
                        ) THEN 'Por confirmar'
                        ELSE 'Sin matrícula'
                    END as estado_estudiante,
                    COUNT(*) as cantidad
                FROM estudiantes_base e
                GROUP BY estado_estudiante
            """)).fetchall()
            
        data = {
            'categorias': {
                'labels': [c[0] for c in categorias],
                'data': [c[1] for c in categorias],
                'colors': ['#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF']
            },
            'estados': {
                'labels': [e[0] for e in estados],
                'data': [e[1] for e in estados],
                'colors': ['#28a745', '#ffc107', '#6c757d']
            }
        }
        return jsonify(data)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)