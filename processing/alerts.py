import logging
from sqlalchemy import select
from database.models import EquipmentSettings, Events, Sensors, ProductionLine
from database.connection import async_session

logger = logging.getLogger(__name__)


async def check_alert_conditions(sensor_id, value, topic=None):
    async with async_session() as session:
        try:
            # Получаем настройки для датчика
            query = select(EquipmentSettings).where(EquipmentSettings.sensor_id == sensor_id)
            result = await session.execute(query)
            setting = result.scalars().first()

            if not setting:
                logger.warning(f"Настройки для датчика {sensor_id} не найдены")
                return  # Настройки не найдены, выходим
                
            # Проверяем, является ли значение числом
            try:
                numeric_value = float(value)
            except (ValueError, TypeError):
                logger.warning(f"Невозможно преобразовать к числу: {value}")
                return

            # Преобразуем граничные значения
            min_value = float(setting.min_value) if setting.min_value is not None else None
            max_value = float(setting.max_value) if setting.max_value is not None else None

            alert_triggered = False
            alert_message = ""

            # Проверяем условия для оповещения
            if min_value is not None and numeric_value < min_value:
                alert_message = f"Значение {numeric_value} ниже допустимого {min_value}"
                alert_triggered = True
                logger.warning(alert_message)
            elif max_value is not None and numeric_value > max_value:
                alert_message = f"Значение {numeric_value} выше допустимого {max_value}"
                alert_triggered = True
                logger.warning(alert_message)
            else:
                logger.debug(f"Значение {numeric_value} в пределах нормы: мин={min_value}, макс={max_value}")

            # Если оповещение сработало, создаем запись в таблице событий
            if alert_triggered:
                # Проверка существования датчика
                sensor_query = select(Sensors).where(Sensors.id == sensor_id)
                sensor_result = await session.execute(sensor_query)
                sensor = sensor_result.scalars().first()

                if sensor:
                    # Получаем информацию о местоположении
                    location_query = select(ProductionLine.name).where(ProductionLine.id == sensor.location)
                    location_result = await session.execute(location_query)
                    location_name = location_result.scalar_one_or_none() or "Неизвестно"
                    
                    # Готовим описание для события
                    description = f"{alert_message} для датчика '{sensor.sensor_name}' ({location_name})"
                    
                    new_event = Events(
                        sensors_id=sensor_id,
                        description=description,
                        users_id=1  # ID пользователя системы по умолчанию
                    )
                    session.add(new_event)
                    await session.commit()
                    logger.info(f"Создано оповещение: {description}")
                else:
                    logger.warning(f"Датчик с id={sensor_id} не найден при создании оповещения")

        except Exception as e:
            logger.error(f"Ошибка при проверке условий оповещения: {e}")