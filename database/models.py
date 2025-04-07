from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, create_engine, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()


class Role(Base):
    __tablename__ = "roles"

    id = Column(BigInteger, primary_key=True)
    roleName = Column(String, unique=True, nullable=False)
    description = Column(String)

    users = relationship("Users", back_populates="role")


class Users(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    name = Column(String)
    login = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"))  # Внешний ключ

    role = relationship("Role", back_populates="users", lazy="joined")
    events = relationship("Events", back_populates="user")


class Sensors(Base):
    __tablename__ = "sensors"

    id = Column(BigInteger, primary_key=True)
    sensor_name = Column(String, nullable=False)
    location = Column(BigInteger)
    active = Column(Boolean, default=True)

    current_values = relationship("CurrentValues", back_populates="sensor")
    equipment_settings = relationship("EquipmentSettings", back_populates="sensor")
    events = relationship("Events", back_populates="sensor")


class CurrentValues(Base):
    __tablename__ = "current_values"

    id = Column(BigInteger, primary_key=True)
    sensors_id = Column(BigInteger, ForeignKey("sensors.id"), nullable=False)
    value = Column(Float, nullable=False)  
    time = Column(DateTime, default=datetime.datetime.now)

    sensor = relationship("Sensors", back_populates="current_values")


class EquipmentSettings(Base):
    __tablename__ = 'equipment_settings'

    id = Column(BigInteger, primary_key=True)
    sensor_id = Column(BigInteger, ForeignKey('sensors.id'))
    max_value = Column(Float)
    min_value = Column(Float)

    sensor = relationship("Sensors", back_populates="equipment_settings")


class Events(Base):
    __tablename__ = "events"

    id = Column(BigInteger, primary_key=True)
    time = Column(DateTime, default=datetime.datetime.now)
    description = Column(String)
    sensors_id = Column(BigInteger, ForeignKey("sensors.id"))
    users_id = Column(BigInteger, ForeignKey("users.id"))

    sensor = relationship("Sensors", back_populates="events")
    user = relationship("Users", back_populates="events")


class ProductionLine(Base):
    __tablename__ = "production_line"

    id = Column(BigInteger, primary_key=True)
    name = Column(String, nullable=False)