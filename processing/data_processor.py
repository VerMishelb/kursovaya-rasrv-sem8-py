import asyncio
import logging
import json
from sqlalchemy import select
from database.connection import async_session
from database.models import CurrentValues, Sensors, Events, EquipmentSettings
from processing.alerts import check_alert_conditions

logger = logging.getLogger(__name__)


async def process_data(topic, data):
    """Асинхронная обработка данных, полученных из MQTT"""
    try:
        logger.debug(f"Обработка данных из топика {topic}: {data}")

        # Если данные пришли в виде строки, преобразуем их в словарь
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                logger.error(f"Невозможно преобразовать данные в JSON: {data}")
                return

        # Проверяем, есть ли в данных идентификатор датчика
        if "sensor_id" in data:
            sensor_id = data["sensor_id"]
        elif "id" in data:
            sensor_id = data["id"]
        else:
            # Пытаемся определить датчик из топика
            async with async_session() as session:
                # Анализируем топик для определения датчика
                topic_parts = topic.split('/')
                if len(topic_parts) >= 2 and topic_parts[0] == "autoclave":
                    # Определяем тип датчика экструдера из топика
                    sensor_type = topic_parts[1]
                    
                    # Сопоставляем топик с типом датчика
                    sensor_type_mapping = {
                        "temperature": "Температура экструдера",
                        "move_speed": "Скорость протяжки",
                        "isolation_thickness": "Толщина изоляции в экструдере",
                        "cable_core_profile": "Сечение жилы",
                    }
                    
                    sensor_name = sensor_type_mapping.get(sensor_type)
                    
                    if sensor_name:
                        # Ищем датчик по имени
                        query = select(Sensors).where(Sensors.sensor_name == sensor_name)
                        result = await session.execute(query)
                        sensor = result.scalars().first()
                        
                        if sensor:
                            sensor_id = sensor.id
                            logger.debug(f"Определен sensor_id={sensor_id} из топика {topic}")
                        else:
                            logger.warning(f"Не удалось найти датчик с именем {sensor_name}")
                            return
                    else:
                        logger.warning(f"Неизвестный тип датчика в топике {topic}")
                        return
                else:
                    logger.warning(f"Неподдерживаемый формат топика {topic}")
                    return

        # Определяем тип значения для сохранения
        if isinstance(data, dict):
            # Извлекаем числовое значение для проверки оповещений
            numeric_value = None

            # Пытаемся найти числовое значение для датчиков экструдера
            for key in ['value', 'temperature', 'move_speed', 'isolation_thickness', 'cable_core_profile']:
                if key in data and isinstance(data[key], (int, float)):
                    numeric_value = data[key]
                    break

            # Если это оповещение, обрабатываем отдельно
            if "alert_type" in data and topic.endswith("/alerts"):
                await process_alert(data)
                return

            # Сохраняем показание датчика
            await save_sensor_reading(sensor_id, numeric_value)
        else:
            # Если это не словарь, сохраняем как есть
            await save_sensor_reading(sensor_id, float(data) if data.replace('.', '', 1).isdigit() else 0)

    except Exception as e:
        logger.error(f"Ошибка обработки данных: {e}")


async def save_sensor_reading(sensor_id, value):
    """Сохранение показаний датчика в БД"""
    async with async_session() as session:
        try:
            # Создаем новую запись показаний датчика
            new_reading = CurrentValues(sensors_id=sensor_id, value=value)
            session.add(new_reading)

            # Проверяем условия для оповещений
            if value is not None:
                await check_alert_conditions(sensor_id, value)

            await session.commit()
            logger.debug(f"Сохранено показание датчика: sensors_id={sensor_id}, value={value}")
        except Exception as e:
            await session.rollback()
            logger.error(f"Ошибка при сохранении показания датчика: {e}")


async def process_alert(data):
    """Обработка оповещений от датчиков"""
    async with async_session() as session:
        try:
            sensor_id = data.get("sensor_id")
            if not sensor_id:
                logger.warning("В оповещении отсутствует sensor_id")
                return
                
            # Ищем датчик в БД
            query = select(Sensors).where(Sensors.id == sensor_id)
            result = await session.execute(query)
            sensor = result.scalars().first()
            
            if not sensor:
                logger.warning(f"Датчик с id={sensor_id} не найден при обработке оповещения")
                return
                
            # Создаем запись в таблице событий
            new_event = Events(
                sensors_id=sensor_id,
                description=data.get("message", "Оповещение без описания"),
                users_id=1  # Пользователь системы по умолчанию
            )
            
            session.add(new_event)
            await session.commit()
            logger.info(f"Создано оповещение: {data.get('message')}, sensor_id={sensor_id}")
            
        except Exception as e:
            logger.error(f"Ошибка при обработке оповещения: {e}")


async def process_extruder_temperature(data):
    logger.debug(f"Обработка данных температуры экструдера: {data}")
    # Здесь может быть дополнительная логика...


async def process_extruder_move_speed(data):
    logger.debug(f"Обработка данных скорости протяжки: {data}")
    # Здесь может быть дополнительная логика...


async def process_extruder_isolation_thickness(data):
    logger.debug(f"Обработка данных толщины изоляции: {data}")
    # Здесь может быть дополнительная логика...


async def process_extruder_cable_core_profile(data):
    logger.debug(f"Обработка данных сечения жилы: {data}")
    # Здесь может быть дополнительная логика...