from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import os
from utils.file_processor import procesar_excel_completo

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
            
            # Últimas matrículas
            ultimas = conn.execute(text("""
                SELECT e.nombre_estudiante, p.programa, m.estado, m.fecha_matricula
                FROM matriculas m
                JOIN estudiantes_base e ON m.estudiante_id = e.id
                JOIN programas p ON m.programa_id = p.id
                ORDER BY m.fecha_carga DESC LIMIT 10
            """)).fetchall()
            
            # Matrículas por programa
            por_programa = conn.execute(text("""
                SELECT p.programa, COUNT(*) as cantidad
                FROM matriculas m
                JOIN programas p ON m.programa_id = p.id
                GROUP BY p.programa
                ORDER BY cantidad DESC LIMIT 10
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
                             ultimas=ultimas,
                             por_programa=por_programa,
                             archivos=archivos)
        
    except Exception as e:
        print(f"Error al cargar datos: {e}")  # Para debug
        flash(f"Error al cargar datos: {str(e)}", "error")
        return render_template('index.html', 
                             stats={}, 
                             ultimas=[], 
                             por_programa=[], 
                             archivos=[])

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

if __name__ == '__main__':
    app.run(debug=True, port=5000)