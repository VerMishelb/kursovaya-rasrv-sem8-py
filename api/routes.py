from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Dict
from database.connection import get_async_session
from database.models import CurrentValues, Sensors, Events, Users, Role, ProductionLine, EquipmentSettings
from datetime import datetime, timedelta
from sqlalchemy import func, select
from api.schemas import SensorOverview, CurrentValueData, EventData, ExtruderSensorData, ExtruderStats
import sqlalchemy as sa
import json

from mqtt.client import logger

router = APIRouter()

# Константы для единиц измерения датчиков экструдера
SENSOR_UNITS = {
    "Температура экструдера": "°C",
    "Скорость протяжки": "м/мин",
    "Толщина изоляции в экструдере": "мм",
    "Сечение жилы": "мм²"
}

@router.get("/sensors", response_model=List[SensorOverview])
async def get_sensors(db: AsyncSession = Depends(get_async_session)):
    """Получение списка всех датчиков"""
    result = await db.execute(select(Sensors))
    sensors = result.scalars().all()
    return sensors


@router.get("/sensors/{sensor_id}/data", response_model=List[CurrentValueData])
async def get_sensor_data(
        sensor_id: int,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
        db: AsyncSession = Depends(get_async_session)
):
    """Получение данных с конкретного датчика за период"""
    query = select(CurrentValues).filter(CurrentValues.sensors_id == sensor_id)

    if from_time:
        query = query.filter(CurrentValues.time >= from_time)
    if to_time:
        query = query.filter(CurrentValues.time <= to_time)
    else:
        # По умолчанию данные за последние 24 часа
        if not from_time:
            query = query.filter(CurrentValues.time >= datetime.now() - timedelta(days=1))

    query = query.order_by(CurrentValues.time)
    result = await db.execute(query)
    readings = result.scalars().all()

    if not readings:
        raise HTTPException(status_code=404, detail="Данные не найдены")

    return readings


@router.get("/alerts")
async def get_alerts(
    from_time: Optional[datetime] = None,
    to_time: Optional[datetime] = None,
    db: AsyncSession = Depends(get_async_session)
):
    """Получение списка оповещений с возможностью фильтрации"""
    try:
        # Проверяем наличие событий без фильтров
        check_query = sa.select(sa.func.count(Events.id))
        count_result = await db.execute(check_query)
        events_count = count_result.scalar() or 0
        
        logger.info(f"Всего найдено событий: {events_count}")
        
        # Основной запрос с минимальными фильтрами
        query = sa.select(
            Events, 
            Sensors.sensor_name
        ).outerjoin(
            Sensors, Events.sensors_id == Sensors.id
        )
        
        # Применяем фильтры
        if from_time:
            query = query.filter(Events.time >= from_time)
                    
        if to_time:
            query = query.filter(Events.time <= to_time)
            
        # Сортировка
        query = query.order_by(Events.time.desc())
        
        result = await db.execute(query)
        alerts = result.all()
        logger.info(f"Найдено оповещений после применения фильтров: {len(alerts)}")
        
        return [
            {
                "id": row.Events.id,
                "time": row.Events.time.isoformat() if row.Events.time else None,
                "description": row.Events.description or "Нет описания",
                "sensors_id": row.Events.sensors_id,
                "users_id": row.Events.users_id,
                "sensor_name": row.sensor_name or "Неизвестно"
            }
            for row in alerts
        ]
    except Exception as e:
        logger.error(f"Ошибка получения оповещений: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/extruder/dashboard")
async def get_extruder_dashboard(db: AsyncSession = Depends(get_async_session)):
    """Получение данных дашборда для экструдера"""
    try:
        # Получаем последние показания всех датчиков экструдера
        location_query = sa.select(ProductionLine.id).where(ProductionLine.name == "экструдер")
        location_result = await db.execute(location_query)
        location_id = location_result.scalar()
        
        if not location_id:
            raise HTTPException(status_code=404, detail="Местоположение 'экструдер' не найдено")
        
        # Получаем все датчики экструдера
        sensors_query = sa.select(Sensors).where(Sensors.location == location_id, Sensors.active == True)
        sensors_result = await db.execute(sensors_query)
        sensors = sensors_result.scalars().all()
        
        sensors_data = []
        
        for sensor in sensors:
            # Получаем последнее показание датчика
            latest_reading_query = sa.select(CurrentValues).where(
                CurrentValues.sensors_id == sensor.id
            ).order_by(CurrentValues.time.desc()).limit(1)
            
            latest_reading_result = await db.execute(latest_reading_query)
            latest_reading = latest_reading_result.scalar_one_or_none()
            
            # Получаем настройки датчика
            settings_query = sa.select(EquipmentSettings).where(
                EquipmentSettings.sensor_id == sensor.id
            )
            settings_result = await db.execute(settings_query)
            settings = settings_result.scalar_one_or_none()
            
            # Получаем имя местоположения
            location_name_query = sa.select(ProductionLine.name).where(
                ProductionLine.id == sensor.location
            )
            location_name_result = await db.execute(location_name_query)
            location_name = location_name_result.scalar_one_or_none() or "Неизвестно"
            
            if latest_reading:
                # Проверяем статус показания
                status = "normal"
                if settings:
                    if latest_reading.value < settings.min_value:
                        status = "low"
                    elif latest_reading.value > settings.max_value:
                        status = "high"
                
                sensors_data.append({
                    "id": sensor.id,
                    "sensor_name": sensor.sensor_name,
                    "location": location_name,
                    "value": float(latest_reading.value),
                    "time": latest_reading.time.isoformat(),
                    "min_value": float(settings.min_value) if settings else None,
                    "max_value": float(settings.max_value) if settings else None,
                    "unit": SENSOR_UNITS.get(sensor.sensor_name, ""),
                    "status": status
                })
        
        # Получаем последние 5 событий/оповещений
        events_query = sa.select(Events, Sensors.sensor_name).join(
            Sensors, Events.sensors_id == Sensors.id
        ).order_by(Events.time.desc()).limit(5)
        
        events_result = await db.execute(events_query)
        events = events_result.all()
        
        recent_events = [
            {
                "id": row.Events.id,
                "time": row.Events.time.isoformat(),
                "description": row.Events.description,
                "sensor_name": row.sensor_name
            }
            for row in events
        ]
        
        return {
            "sensors": sensors_data,
            "recent_events": recent_events
        }
        
    except Exception as e:
        logger.error(f"Ошибка получения данных для дашборда экструдера: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/extruder/statistics")
async def get_extruder_statistics(
    from_time: Optional[datetime] = None,
    to_time: Optional[datetime] = None,
    db: AsyncSession = Depends(get_async_session)
):
    try:
        if not from_time:
            from_time = datetime.now() - timedelta(days=1)
        if not to_time:
            to_time = datetime.now()
            
        # Находим ID локации "экструдер"
        location_query = sa.select(ProductionLine.id).where(ProductionLine.name == "экструдер")
        location_result = await db.execute(location_query)
        location_id = location_result.scalar()
        
        if not location_id:
            raise HTTPException(status_code=404, detail="Местоположение 'экструдер' не найдено")
        
        # Находим все датчики экструдера
        sensors_query = sa.select(Sensors).where(Sensors.location == location_id)
        sensors_result = await db.execute(sensors_query)
        sensors = {s.sensor_name: s.id for s in sensors_result.scalars().all()}
        
        result = {}
        
        # Для каждого типа датчика получаем статистику
        for sensor_name, sensor_id in sensors.items():
            # Получаем показания за период
            readings_query = sa.select(
                CurrentValues.time, 
                CurrentValues.value
            ).where(
                CurrentValues.sensors_id == sensor_id,
                CurrentValues.time.between(from_time, to_time)
            ).order_by(CurrentValues.time)
            
            readings_result = await db.execute(readings_query)
            readings = readings_result.all()
            
            # Вычисляем статистику
            values = [float(r.value) for r in readings]
            
            if values:
                avg_value = sum(values) / len(values)
                min_value = min(values)
                max_value = max(values)
                
                # Получаем настройки для проверки отклонений
                settings_query = sa.select(EquipmentSettings).where(
                    EquipmentSettings.sensor_id == sensor_id
                )
                settings_result = await db.execute(settings_query)
                settings = settings_result.scalar_one_or_none()
                
                # Считаем отклонения, если есть настройки
                deviations = 0
                if settings:
                    for value in values:
                        if value < settings.min_value or value > settings.max_value:
                            deviations += 1
                
                # Выбираем ключ для словаря статистики
                key = sensor_name.lower().replace(" ", "_")
                key = key.replace("температура_экструдера", "temperature")
                key = key.replace("сечение_жилы", "cable_core_profile")
                
                short_name = sensor_name
                if "температуры" in sensor_name.lower():
                    short_name = "Температура"
                    key = "temperature"
                elif "скорости протяжки" in sensor_name.lower():
                    short_name = "Скорость протяжки"
                    key = "move_speed"
                elif "толщина изоляции" in sensor_name.lower():
                    short_name = "Толщина изоляции"
                    key = "isolation_thickness"
                
                # Формируем статистику
                result[key] = {
                    "sensor_name": short_name,
                    "avg_value": round(avg_value, 2),
                    "min_value": round(min_value, 2),
                    "max_value": round(max_value, 2),
                    "unit": SENSOR_UNITS.get(sensor_name, ""),
                    "deviations": deviations,
                    "deviation_percent": round(deviations / len(values) * 100, 1) if values else 0,
                    "readings_count": len(values)
                }
            else:
                result[sensor_name.lower().replace(" ", "_")] = {
                    "sensor_name": sensor_name,
                    "avg_value": 0,
                    "min_value": 0,
                    "max_value": 0,
                    "unit": SENSOR_UNITS.get(sensor_name, ""),
                    "deviations": 0,
                    "deviation_percent": 0,
                    "readings_count": 0
                }
        
        return result
        
    except Exception as e:
        logger.error(f"Ошибка получения статистики экструдера: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sensors/latest")
async def get_latest_sensor_data(db: AsyncSession = Depends(get_async_session)):
    try:
        # Подзапрос для получения последнего времени для каждого датчика
        latest_time_subquery = sa.select(
            CurrentValues.sensors_id,
            sa.func.max(CurrentValues.time).label("latest_time")
        ).group_by(CurrentValues.sensors_id).subquery()
        
        # Основной запрос с джойнами для получения всей информации
        query = sa.select(
            CurrentValues, 
            Sensors.sensor_name, 
            ProductionLine.name.label("location_name"),
            EquipmentSettings.min_value,
            EquipmentSettings.max_value
        ).join(
            latest_time_subquery,
            sa.and_(
                CurrentValues.sensors_id == latest_time_subquery.c.sensors_id,
                CurrentValues.time == latest_time_subquery.c.latest_time
            )
        ).join(
            Sensors, CurrentValues.sensors_id == Sensors.id
        ).join(
            ProductionLine, Sensors.location == ProductionLine.id
        ).outerjoin(
            EquipmentSettings, Sensors.id == EquipmentSettings.sensor_id
        ).order_by(ProductionLine.name, Sensors.sensor_name)
        
        result = await db.execute(query)
        rows = result.all()
        
        return [
            {
                "sensor_id": row.CurrentValues.sensors_id,
                "sensor_name": row.sensor_name,
                "location": row.location_name,
                "value": float(row.CurrentValues.value),
                "time": row.CurrentValues.time.isoformat(),
                "min_value": float(row.min_value) if row.min_value is not None else None,
                "max_value": float(row.max_value) if row.max_value is not None else None,
                "unit": SENSOR_UNITS.get(row.sensor_name, ""),
                "status": get_sensor_status(float(row.CurrentValues.value), row.min_value, row.max_value)
            }
            for row in rows
        ]
    except Exception as e:
        logger.error(f"Ошибка получения данных датчиков: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def get_sensor_status(value, min_value, max_value):
    # Функция для определения статуса датчика с учетом возможных None-значений
    try:
        # Проверяем условия только если значения не None
        if min_value is not None and value < min_value:
            return "low"
        elif max_value is not None and value > max_value:
            return "high"
        else:
            return "normal"
    except (ValueError, TypeError):
        # В случае ошибки конвертации возвращаем "normal"
        return "normal"