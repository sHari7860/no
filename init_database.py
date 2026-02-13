from models import init_db

if __name__ == '__main__':
    print('Creando base de datos y tablas en PostgreSQL...')
    init_db()
    print('¡Base de datos creada exitosamente!')
