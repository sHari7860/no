from models import init_db


def init_database():
    init_db()
    return True


if __name__ == '__main__':
    print('Inicializando base de datos PostgreSQL...')
    init_database()
    print('Listo.')
