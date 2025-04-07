import asyncio
import logging
import random
import json
from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import select

from database.connection import engine, async_session
from database.models import Role, Users, Sensors, CurrentValues, EquipmentSettings, Events, ProductionLine, Base


logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Тестовые данные
ROLES = [
    {"roleName": "admin", "description": "Администратор системы"},
    {"roleName": "technician", "description": "Технический специалист"}
]

USERS = [
    {"name": "admin", "login": "admin", "password": "12345", "role": "admin"},
    {"name": "operator", "login": "tech", "password": "12345", "role": "technician"}
]

LOCATIONS = [
    {"name": "Экструдер"}
]

# Датчики экструдера из таблицы
SENSORS = [
    {"sensor_name": "Температура экструдера", "location": "Экструдер", "active": True},
    {"sensor_name": "Скорость протяжки", "location": "Экструдер", "active": True},
    {"sensor_name": "Толщина изоляции", "location": "Экструдер", "active": True},
    {"sensor_name": "Сечение жилы", "location": "Экструдер", "active": True}
]

# Настройки для датчиков экструдера
EQUIPMENT_SETTINGS = [
    {"sensor_name": "Температура экструдера", "min_value": 160, "max_value": 180},
    {"sensor_name": "Скорость протяжки", "min_value": 30, "max_value": 40},
    {"sensor_name": "Толщина изоляции", "min_value": 1.8, "max_value": 2},
    {"sensor_name": "Сечение жилы", "min_value": 49.8, "max_value": 50.2}
]

# Единицы измерения датчиков
SENSOR_UNITS = {
    "Температура экструдера": "°C",
    "Скорость протяжки": "м/мин",
    "Толщина изоляции": "мм",
    "Сечение жилы": "мм²",
}


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("Таблицы успешно созданы.")


async def create_roles():
    async with async_session() as session:
        try:
            existing_query = select(Role)
            existing_result = await session.execute(existing_query)
            existing_roles = existing_result.scalars().all()

            if existing_roles:
                logger.info(f"Найдено существующих ролей: {len(existing_roles)}")
                return {role.roleName: role for role in existing_roles}

            # Создаем роли
            roles = []
            for role_data in ROLES:
                role = Role(**role_data)
                roles.append(role)
                session.add(role)

            await session.commit()
            logger.info(f"Создано ролей: {len(roles)}")

            # Возвращаем словарь ролей для использования в других функциях
            role_dict = {}
            for role in roles:
                await session.refresh(role)
                role_dict[role.roleName] = role

            return role_dict
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка при создании ролей: {e}")
            raise

# Тестовые пользователи
async def create_users(roles):
    async with async_session() as session:
        try:
            existing_query = select(Users)
            existing_result = await session.execute(existing_query)
            existing_users = existing_result.scalars().all()

            users = []
            for user_data in USERS:
                role_name = user_data.pop("role")
                
                user = Users(
                    **user_data,
                    role_id=roles[role_name].id
                )
                users.append(user)
                session.add(user)

            await session.commit()
            logger.info(f"Создано пользователей: {len(users)}")
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка при создании пользователей: {e}")
            raise


async def create_locations():
    async with async_session() as session:
        try:
            locations_dict = {}
            for loc_data in LOCATIONS:
                location_query = select(ProductionLine).where(ProductionLine.name == loc_data["name"])
                location_result = await session.execute(location_query)
                location = location_result.scalars().first()
                
                if location:
                    locations_dict[location.name] = location.id
                else:
                    new_location = ProductionLine(name=loc_data["name"])
                    session.add(new_location)
                    await session.flush() 
                    locations_dict[new_location.name] = new_location.id
            
            await session.commit()
            logger.info(f"Изменено местоположений: {len(locations_dict)}")
            return locations_dict
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка при создании местоположений: {e}")
            raise


async def create_sensors(locations):
    async with async_session() as session:
        try:
            existing_query = select(Sensors)
            existing_result = await session.execute(existing_query)
            existing_sensors = existing_result.scalars().all()

            if existing_sensors:
                logger.info(f"Найдено существующих датчиков: {len(existing_sensors)}")
                extruder_query = select(Sensors).join(ProductionLine, 
                                                      Sensors.location == ProductionLine.id)\
                                                .where(ProductionLine.name == "Экструдер")
                extruder_result = await session.execute(extruder_query)
                extruder_sensors = extruder_result.scalars().all()
                
                if extruder_sensors and len(extruder_sensors) >= 6:
                    logger.info(f"Найдено {len(extruder_sensors)} датчиков в зоне экструдера.")
                    return existing_sensors
            
            # Создаем датчики
            sensors = []
            for sensor_data in SENSORS:
                location_name = sensor_data.pop("location")
                location_id = locations[location_name]
                
                sensor = Sensors(
                    sensor_name=sensor_data["sensor_name"],
                    location=location_id,
                    active=sensor_data["active"]
                )
                sensors.append(sensor)
                session.add(sensor)

            await session.commit()
            logger.info(f"Создано датчиков: {len(sensors)}")

            return sensors
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка при создании датчиков: {e}")
            raise


async def create_equipment_settings(sensors):
    async with async_session() as session:
        try:
            # Все датчики
            sensor_query = select(Sensors)
            sensor_result = await session.execute(sensor_query)
            all_sensors = {s.sensor_name: s for s in sensor_result.scalars().all()}
            
            # Проверяем наличие существующих настроек
            existing_settings = {}
            for sensor_name, sensor in all_sensors.items():
                settings_query = select(EquipmentSettings).where(EquipmentSettings.sensor_id == sensor.id)
                settings_result = await session.execute(settings_query)
                setting = settings_result.scalars().first()
                if setting:
                    existing_settings[sensor_name] = setting
            
            # Если настройки уже существуют для всех датчиков экструдера, не трогать
            if all(s["sensor_name"] in existing_settings for s in EQUIPMENT_SETTINGS):
                logger.info("Настройки для всех датчиков экструдера уже существуют")
                return
            
            # Создаем настройки для датчиков экструдера
            settings = []
            for sensor_setting in EQUIPMENT_SETTINGS:
                sensor_name = sensor_setting["sensor_name"]
                if sensor_name in all_sensors and sensor_name not in existing_settings:
                    setting = EquipmentSettings(
                        sensor_id=all_sensors[sensor_name].id,
                        min_value=sensor_setting["min_value"],
                        max_value=sensor_setting["max_value"]
                    )
                    settings.append(setting)
                    session.add(setting)
            
            if settings:
                await session.commit()
                logger.info(f"Создано настроек оборудования: {len(settings)}")
            else:
                logger.info("Нет новых настроек для создания.")
                
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка при создании настроек оборудования: {e}")
            raise

# Датчиков у нас нет, поэтому делаем вид, что есть
async def generate_sensor_readings():
    async with async_session() as session:
        try:
            # Получаем все датчики экструдера с настройками
            sensors_query = select(Sensors).join(
                EquipmentSettings, 
                Sensors.id == EquipmentSettings.sensor_id
            )
            sensors_result = await session.execute(sensors_query)
            sensors_with_settings = []
            
            for sensor in sensors_result.scalars().all():
                # Получаем настройки для датчика
                settings_query = select(EquipmentSettings).where(
                    EquipmentSettings.sensor_id == sensor.id
                )
                settings_result = await session.execute(settings_query)
                settings = settings_result.scalars().first()
                
                if settings:
                    sensors_with_settings.append({
                        "sensor": sensor,
                        "settings": settings,
                        "unit": SENSOR_UNITS.get(sensor.sensor_name, "")
                    })
            
            # Генерируем текущие значения для датчиков
            current_time = datetime.now()
            for sensor_data in sensors_with_settings:
                sensor = sensor_data["sensor"]
                settings = sensor_data["settings"]
                unit = sensor_data["unit"]
                
                # Генерируем значение в пределах min и max
                value = random.uniform(float(settings.min_value), float(settings.max_value))
                
                # Создаем запись текущего значения
                current_value = CurrentValues(
                    sensors_id=sensor.id,
                    value=value,
                    time=current_time
                )
                session.add(current_value)
                
                # Генерируем информативное событие
                event = Events(
                    time=current_time,
                    description=f"Измереное значение датчика '{sensor.sensor_name}': {round(value, 2)} {unit}",
                    sensors_id=sensor.id,
                    users_id=1  # Администратор
                )
                session.add(event)
            
            await session.commit()
            logger.info(f"Созданы показания для {len(sensors_with_settings)} датчиков.")
            
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка при создании показаний датчиков: {e}")
            raise

# Инициализация БД
async def main():
    try:
        await create_tables()
        roles = await create_roles()
        await create_users(roles)
        locations = await create_locations()
        sensors = await create_sensors(locations)
        await create_equipment_settings(sensors)
        await generate_sensor_readings()

        logger.info("БД инициализована.")

    except Exception as e:
        logger.error(f"Ошибка при инициализации базы данных: {e}")


if __name__ == "__main__":
    asyncio.run(main())