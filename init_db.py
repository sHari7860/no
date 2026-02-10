# init_db.py
from connection import engine, Base
from models import Estudiante, Programa, Periodo, Matricula, ArchivoProcesado
import sys

def init_database():
    """Crear todas las tablas en la base de datos"""
    print("=== INICIALIZACIÓN DE BASE DE DATOS ===")
    print("-" * 50)
    
    try:
        # Crear todas las tablas
        print("Creando tablas...")
        Base.metadata.create_all(bind=engine)
        
        print("✅ Tablas creadas exitosamente:")
        print("   • estudiantes")
        print("   • programas")
        print("   • periodos")
        print("   • matriculas")
        print("   • archivos_procesados")
        
        # Verificar
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name
            """))
            
            print(f"\n📊 Tablas en la base de datos: {result.rowcount}")
            for row in result:
                print(f"   • {row[0]}")
        
        print("\n" + "=" * 50)
        print("✅ BASE DE DATOS LISTA PARA USAR")
        print("=" * 50)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    success = init_database()
    sys.exit(0 if success else 1)