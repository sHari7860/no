from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
import os
import sqlite3
from werkzeug.utils import secure_filename
from datetime import datetime
import json
from database import init_app, get_db_connection
from import_data import import_excel_to_db

app = Flask(__name__)
app.config['SECRET_KEY'] = 'clave-secreta-para-flask'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB máximo

# Asegurar que la carpeta de uploads existe
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Extensiones permitidas
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    """Página principal con dashboard"""
    conn = get_db_connection()
    
    # Obtener estadísticas generales
    cursor = conn.cursor()
    
    # Total estudiantes
    cursor.execute('SELECT COUNT(*) FROM estudiantes')
    total_estudiantes = cursor.fetchone()[0]
    
    # Total matrículas
    cursor.execute('SELECT COUNT(*) FROM matriculas')
    total_matriculas = cursor.fetchone()[0]
    
    # Total programas
    cursor.execute('SELECT COUNT(*) FROM programas')
    total_programas = cursor.fetchone()[0]
    
    # Último archivo importado
    cursor.execute('''
        SELECT nombre_archivo, fecha_importacion, total_registros 
        FROM archivos_importados 
        ORDER BY fecha_importacion DESC LIMIT 1
    ''')
    ultimo_archivo = cursor.fetchone()
    
    # Estadísticas por categoría
    cursor.execute('''
        SELECT c.nombre, COUNT(m.id) 
        FROM matriculas m
        JOIN categorias c ON m.categoria_id = c.id
        GROUP BY c.nombre
    ''')
    stats_categoria = cursor.fetchall()
    
    # Top 10 programas más solicitados
    cursor.execute('''
        SELECT p.nombre_original, COUNT(m.id) as total
    FROM matriculas m
    JOIN programas p ON m.programa_id = p.id
    JOIN estados_matricula e ON m.estado_matricula_id = e.id
    WHERE e.nombre = 'Confirmado'  -- FILTRO CRÍTICO
    GROUP BY p.nombre_original
    ORDER BY total DESC
    LIMIT 10
    ''')
    top_programas = cursor.fetchall()
    
    # Estadísticas por período
    cursor.execute('''
        SELECT pr.codigo_periodo, COUNT(m.id) as total
        FROM matriculas m
        JOIN periodos pr ON m.periodo_id = pr.id
        GROUP BY pr.codigo_periodo
        ORDER BY pr.codigo_periodo DESC
    ''')
    stats_periodo = cursor.fetchall()
    
    conn.close()
    
    return render_template('dashboard.html',
                         total_estudiantes=total_estudiantes,
                         total_matriculas=total_matriculas,
                         total_programas=total_programas,
                         ultimo_archivo=ultimo_archivo,
                         stats_categoria=stats_categoria,
                         top_programas=top_programas,
                         stats_periodo=stats_periodo)

@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    """Página para cargar archivos Excel"""
    if request.method == 'POST':
        # Verificar si se envió un archivo
        if 'file' not in request.files:
            flash('No se seleccionó ningún archivo', 'error')
            return redirect(request.url)
        
        file = request.files['file']
        
        if file.filename == '':
            flash('No se seleccionó ningún archivo', 'error')
            return redirect(request.url)
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Guardar el archivo
            file.save(filepath)
            
            # Importar a la base de datos
            result = import_excel_to_db(filepath, filename)
            
            if 'error' in result:
                flash(result['error'], 'error')
                os.remove(filepath)  # Eliminar archivo si hay error
            else:
                flash(f'Archivo importado exitosamente: {result["nuevas_matriculas"]} nuevas matrículas agregadas', 'success')
                flash(f'Período: {result["periodo"]}, Total registros: {result["total_registros"]}', 'info')
            
            return redirect(url_for('index'))
        else:
            flash('Tipo de archivo no permitido. Solo se aceptan Excel (.xlsx, .xls)', 'error')
            return redirect(request.url)
    
    return render_template('upload.html')

@app.route('/api/estadisticas')
def get_estadisticas():
    """API para obtener estadísticas en formato JSON"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Datos para gráficos
    cursor.execute('''
        SELECT c.nombre, COUNT(m.id) 
        FROM matriculas m
        JOIN categorias c ON m.categoria_id = c.id
        GROUP BY c.nombre
    ''')
    categorias_data = cursor.fetchall()
    
    cursor.execute('''
        SELECT p.tipo_programa, COUNT(m.id) 
        FROM matriculas m
        JOIN programas p ON m.programa_id = p.id
        GROUP BY p.tipo_programa
    ''')
    tipos_programa_data = cursor.fetchall()
    
    cursor.execute('''
        SELECT e.nombre, COUNT(m.id) 
        FROM estados_matricula e
        JOIN matriculas m ON m.estado_matricula_id = e.id
        GROUP BY e.nombre
    ''')
    estados_data = cursor.fetchall()
    
    # Evolución por período
    cursor.execute('''
        SELECT pr.codigo_periodo, COUNT(DISTINCT m.estudiante_id)
        FROM matriculas m
        JOIN periodos pr ON m.periodo_id = pr.id
        GROUP BY pr.codigo_periodo
        ORDER BY pr.codigo_periodo
    ''')
    evolucion_data = cursor.fetchall()
    
    conn.close()
    
    # Formatear datos para gráficos
    data = {
        'categorias': {
            'labels': [row[0] for row in categorias_data],
            'data': [row[1] for row in categorias_data]
        },
        'tipos_programa': {
            'labels': [row[0] for row in tipos_programa_data],
            'data': [row[1] for row in tipos_programa_data]
        },
        'estados': {
            'labels': [row[0] for row in estados_data],
            'data': [row[1] for row in estados_data]
        },
        'evolucion': {
            'labels': [row[0] for row in evolucion_data],
            'data': [row[1] for row in evolucion_data]
        }
    }
    
    return jsonify(data)

@app.route('/data')
def view_data():
    """Página para ver los datos almacenados"""
    conn = get_db_connection()
    
    # Obtener parámetros de filtro
    periodo = request.args.get('periodo', '')
    programa = request.args.get('programa', '')
    categoria = request.args.get('categoria', '')
    page = int(request.args.get('page', 1))
    per_page = 50
    
    # Construir consulta con filtros
    query = '''
        SELECT 
            e.documento,
            e.nombre_completo,
            pr.nombre_original as programa,
            pr.tipo_programa,
            per.codigo_periodo,
            c.nombre as categoria,
            em.nombre as estado,
            m.fecha_inscripcion,
            m.liquidacion_numero,
            m.novedad
        FROM matriculas m
        JOIN estudiantes e ON m.estudiante_id = e.id
        JOIN programas pr ON m.programa_id = pr.id
        JOIN periodos per ON m.periodo_id = per.id
        JOIN categorias c ON m.categoria_id = c.id
        JOIN estados_matricula em ON m.estado_matricula_id = em.id
        WHERE 1=1
    '''
    
    params = []
    
    if periodo:
        query += ' AND per.codigo_periodo = ?'
        params.append(periodo)
    
    if programa:
        query += ' AND pr.nombre_normalizado LIKE ?'
        params.append(f'%{programa}%')
    
    if categoria:
        query += ' AND c.nombre = ?'
        params.append(categoria)
    
    query += ' ORDER BY m.fecha_inscripcion DESC'
    
    # Contar total
    count_query = f'SELECT COUNT(*) FROM ({query})'
    cursor = conn.cursor()
    cursor.execute(count_query, params)
    total = cursor.fetchone()[0]
    
    # Paginación
    query += ' LIMIT ? OFFSET ?'
    params.extend([per_page, (page - 1) * per_page])
    
    cursor.execute(query, params)
    datos = cursor.fetchall()
    
    # Obtener opciones para filtros
    cursor.execute('SELECT DISTINCT codigo_periodo FROM periodos ORDER BY codigo_periodo DESC')
    periodos = cursor.fetchall()
    
    cursor.execute('SELECT DISTINCT nombre FROM categorias ORDER BY nombre')
    categorias_list = cursor.fetchall()
    
    cursor.execute('SELECT DISTINCT nombre_original FROM programas ORDER BY nombre_original')
    programas_list = cursor.fetchall()
    
    conn.close()
    
    total_pages = (total + per_page - 1) // per_page
    
    return render_template('data.html',
                         datos=datos,
                         periodos=periodos,
                         categorias=categorias_list,
                         programas=programas_list,
                         periodo_actual=periodo,
                         categoria_actual=categoria,
                         programa_actual=programa,
                         page=page,
                         total_pages=total_pages,
                         total=total)

@app.route('/export')
def export_data():
    """Exportar datos a CSV"""
    conn = get_db_connection()
    
    query = '''
        SELECT 
            e.documento,
            e.nombre_completo,
            pr.nombre_original as programa,
            pr.tipo_programa,
            per.codigo_periodo,
            c.nombre as categoria,
            em.nombre as estado,
            m.fecha_inscripcion,
            m.liquidacion_numero,
            e.correo_personal,
            e.correo_institucional,
            m.novedad
        FROM matriculas m
        JOIN estudiantes e ON m.estudiante_id = e.id
        JOIN programas pr ON m.programa_id = pr.id
        JOIN periodos per ON m.periodo_id = per.id
        JOIN categorias c ON m.categoria_id = c.id
        JOIN estados_matricula em ON m.estado_matricula_id = em.id
        ORDER BY per.codigo_periodo DESC, e.nombre_completo
    '''
    
    cursor = conn.cursor()
    cursor.execute(query)
    datos = cursor.fetchall()
    
    # Crear archivo CSV
    import csv
    from io import StringIO
    
    output = StringIO()
    writer = csv.writer(output)
    
    # Escribir encabezados
    writer.writerow(['Documento', 'Nombre', 'Programa', 'Tipo Programa', 'Período',
                    'Categoría', 'Estado', 'Fecha Inscripción', 'Liquidación',
                    'Correo Personal', 'Correo Institucional', 'Novedad'])
    
    # Escribir datos
    for row in datos:
        writer.writerow(row)
    
    conn.close()
    
    output.seek(0)
    
    return send_file(
        output,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'matriculas_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

if __name__ == '__main__':
    # Inicializar la base de datos
    init_app()
    
    # Ejecutar la aplicación
    app.run(debug=True, port=5000)