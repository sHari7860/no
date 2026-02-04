from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class Estudiante(Base):
    __tablename__ = 'estudiantes_base'
    
    id = Column(Integer, primary_key=True, index=True)
    documento = Column(String(50), unique=True, nullable=False)
    nombre_estudiante = Column(String)
    correo_personal = Column(String)
    correo_institucional = Column(String)
    categoria = Column(String)
    fecha_creacion = Column(DateTime, default=datetime.now)
    
    # Relación
    matriculas = relationship("Matricula", back_populates="estudiante")

class Programa(Base):
    __tablename__ = 'programas'
    
    id = Column(Integer, primary_key=True, index=True)
    codigo_programa = Column(String(20))
    programa = Column(String, unique=True, nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.now)
    
    # Relación
    matriculas = relationship("Matricula", back_populates="programa")

class Periodo(Base):
    __tablename__ = 'periodos'
    
    id = Column(Integer, primary_key=True, index=True)
    periodo = Column(String, unique=True, nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.now)
    
    # Relación
    matriculas = relationship("Matricula", back_populates="periodo")

class Matricula(Base):
    __tablename__ = 'matriculas'
    
    id = Column(Integer, primary_key=True, index=True)
    estudiante_id = Column(Integer, ForeignKey('estudiantes_base.id'))
    programa_id = Column(Integer, ForeignKey('programas.id'))
    periodo_id = Column(Integer, ForeignKey('periodos.id'))
    estado = Column(String)
    fecha_matricula = Column(String)
    fecha_carga = Column(DateTime, default=datetime.now)
    archivo_origen = Column(String)
    
    # Relaciones
    estudiante = relationship("Estudiante", back_populates="matriculas")
    programa = relationship("Programa", back_populates="matriculas")
    periodo = relationship("Periodo", back_populates="matriculas")