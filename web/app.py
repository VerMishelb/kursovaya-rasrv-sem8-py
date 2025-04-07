from fastapi import FastAPI, Request, Depends, HTTPException, status, Form, Response, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
from database.connection import get_async_session
from database.models import Users, Role, CurrentValues, Sensors, ProductionLine, Events, EquipmentSettings
from api.routes import router as api_router
from api.schemas import LoginRequest, TokenResponse
from jose import jwt, JWTError, ExpiredSignatureError
from datetime import datetime, timedelta
from config import config
import sqlalchemy as sa
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import typing
from web.websockets import manager
import logging
import asyncio
import random
from sqlalchemy.orm import joinedload
import traceback
import json

logger = logging.getLogger(__name__)

app = FastAPI(title="Система мониторинга экструдера")

# Подключение статических файлов и шаблонов
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Настройка OAuth2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Константы для единиц измерения датчиков экструдера
SENSOR_UNITS = {
    "Температура экструдера": "°C",
    "Скорость протяжки": "м/мин",
    "Толщина изоляции": "мм",
    "Сечение жилы": "мм²"
}


# Создание токена доступа
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=24)
    to_encode.update({"exp": expire})
    # Используем JWT из jose
    encoded_jwt = jwt.encode(to_encode, config.SECRET_KEY, algorithm=config.ALGORITHM)
    return encoded_jwt


# Верификация пользователя
async def authenticate_user(db: AsyncSession, login: str, password: str):
    """Аутентификация пользователя"""
    try:
        # Ищем пользователя по логину
        query = select(Users).where(Users.login == login)
        result = await db.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            return None
        if user.password != password:
            return None

        return user
    except Exception as e:
        logger.error(f"Ошибка аутентификации: {e}")
        return None


async def get_current_user_from_cookie(request: Request, db: AsyncSession = Depends(get_async_session)):
    try:
        token = request.cookies.get('access_token')
        if not token:
            logger.warning("Токен отсутствует в cookie")
            return None

        # Извлекаем сам токен из строки "Bearer ..."
        if token.startswith("Bearer "):
            token = token.split("Bearer ")[1]

        # Упрощенная проверка - без верификации подписи
        try:
            # Только для отладки - распаковываем без проверки подписи
            decoded_payload = jwt.decode(
                token,
                config.SECRET_KEY,  # Используем правильный ключ из конфигурации
                options={"verify_signature": False}
            )
            login = decoded_payload.get("sub")
            role = decoded_payload.get("role")

            logger.info(f"Декодирован токен для пользователя: {login}, роль: {role}")

            # Создаем временный объект пользователя для отладки
            if login in ["admin", "operator"]:
                user = type('User', (), {
                    'login': login,
                    'role': role or ("admin" if login == "admin" else "operator")
                })
                return user

        except Exception as decode_error:
            logger.error(f"Ошибка при базовом декодировании токена: {decode_error}")

        # Пытаемся найти пользователя в БД (если он там есть)
        try:
            # Более безопасное декодирование с проверкой подписи
            payload = jwt.decode(token, config.SECRET_KEY, algorithms=["HS256"])
            login = payload.get("sub")

            if login:
                # Ищем в БД
                query = sa.select(Users).where(Users.login == login)
                result = await db.execute(query)
                user = result.scalars().first()

                if user:
                    return user
        except Exception as e:
            logger.warning(f"Ошибка при проверке токена с подписью: {e}")
            # Продолжаем использовать упрощенный вариант без проверки подписи

        return None

    except Exception as e:
        logger.error(f"Общая ошибка при получении пользователя из cookie: {e}")
        return None


# Подключение API маршрутов
app.include_router(api_router, prefix="/api")


@app.post("/token")
async def login_for_access_token(
        response: Response,
        form_data: OAuth2PasswordRequestForm = Depends(),
        db: AsyncSession = Depends(get_async_session)
):
    """Получение токена доступа - совсем простая версия"""
    try:
        # Получаем пользователя
        query = select(Users).where(Users.login == form_data.username)
        result = await db.execute(query)
        user = result.scalar_one_or_none()

        if not user or user.password != form_data.password:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Неверное имя пользователя или пароль{user.password} {form_data.password}",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Получаем роль пользователя
        role_query = select(Role).where(Role.id == user.role_id)
        role_result = await db.execute(role_query)
        role = role_result.scalar_one_or_none()
        role_value = role.roleName if role else "operator"

        # Создаем JWT токен
        access_token_expires = timedelta(minutes=60)
        access_token = create_access_token(
            data={"sub": user.login, "role": role_value},
            expires_delta=access_token_expires
        )

        # Устанавливаем cookie
        response.set_cookie(
            key="access_token",
            value=f"Bearer {access_token}",
            httponly=True,
            max_age=3600,
            path="/",
            samesite="lax"
        )

        return {"access_token": access_token, "token_type": "bearer"}

    except Exception as e:
        logger.error(f"Ошибка при авторизации: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )


@app.get("/")
async def root():
    return {"message": "Система мониторинга экструдера работает!"}


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/dashboard"):
    """Страница входа с формой авторизации"""
    return templates.TemplateResponse("login.html", {
        "request": request,
        "next": next,
        "user": None
    })


@app.post("/login")
async def login_form(
        request: Request,
        login: str = Form(...),
        password: str = Form(...),
        next: str = Form("/dashboard")  # Параметр для перенаправления
):
    """Максимально упрощенная обработка формы входа"""
    try:
        # Проверяем логин/пароль напрямую, без запросов к БД
        valid_credentials = {
            "admin": "admin",
            "operator": "operator"
        }

        if login not in valid_credentials or password != valid_credentials[login]:
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Неверное имя пользователя или пароль", "next": next}
            )

        # Роль правильная - admin для adminbd_, operator для operator
        role = "admin" if login == "admin" else "operator"

        # Создаем JWT токен с минимальными данными
        token_data = {
            "sub": login,
            "role": role,  # Используем правильную роль
            "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp())
        }

        # Логируем, чтобы видеть, что передается
        logger.info(f"Создаем токен для пользователя {login} с ролью {role}")

        # Кодируем токен напрямую
        access_token = jwt.encode(token_data, config.SECRET_KEY, algorithm="HS256")

        # Создаем ответ с редиректом на исходную страницу
        response = RedirectResponse(url=next, status_code=303)

        # Добавляем cookie максимально просто
        response.set_cookie(
            key="access_token",
            value=f"Bearer {access_token}",
            path="/",
            httponly=True,
            max_age=3600
        )

        return response

    except Exception as e:
        logger.error(f"Ошибка при обработке формы входа: {e}")
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": f"Ошибка сервера: {str(e)}", "next": next}
        )


@app.get("/dashboard")
async def dashboard(request: Request, db: AsyncSession = Depends(get_async_session)):
    """Защищенная страница с проверкой пользователя из cookie"""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url='/login?next=/dashboard')

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "username": getattr(user, 'login', 'Гость'),
            "role": getattr(user, 'role', 'guest'),
            "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    )


@app.get("/sensors")
async def sensors_page(request: Request, db: AsyncSession = Depends(get_async_session)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url=f'/login?next=/sensors')

    return templates.TemplateResponse("sensors.html", {
        "request": request,
        "user": user
    })


@app.get("/alerts")
async def alerts_page(request: Request, db: AsyncSession = Depends(get_async_session)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url=f'/login?next=/alerts')

    # Получаем токен из cookie для передачи в шаблон
    token = request.cookies.get('access_token', '')

    return templates.TemplateResponse("alerts.html", {
        "request": request,
        "user": user,
        "token": token  # Передаем токен в шаблон
    })


@app.get("/reports")
async def reports_page(request: Request, db: AsyncSession = Depends(get_async_session)):
    user = await get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url=f'/login?next=/reports')

    return templates.TemplateResponse("reports.html", {
        "request": request,
        "user": user
    })


# Добавьте маршрут для выхода из системы
@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(key="access_token", path="/")
    return response


# Маршрут для WebSocket дашборда
@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket, db: AsyncSession = Depends(get_async_session)):
    await websocket.accept()

    try:
        while True:
            # Получаем данные для дашборда
            try:
                dashboard_data = await generate_dashboard_data(db)
                await websocket.send_json(dashboard_data)
            except Exception as e:
                logger.error(f"Ошибка при генерации данных дашборда: {e}")
                # Создаем новую сессию для следующей попытки
                await websocket.send_json({
                    "error": "Ошибка получения данных дашборда",
                    "sensor_readings": [],
                    "recent_events": [],
                    "extruder_status": {
                        "status": "error",
                        "message": "Ошибка получения данных",
                        "metrics": {}
                    }
                })

            # Ждем перед следующим обновлением
            await asyncio.sleep(1)

    except WebSocketDisconnect:
        logger.info("WebSocket клиент отключен от /ws/dashboard")
    except Exception as e:
        logger.error(f"Ошибка при отправке данных дашборда: {e}")
        try:
            await websocket.send_json({"error": f"Ошибка получения данных дашборда: {str(e)}"})
        except:
            pass


async def generate_dashboard_data(db: AsyncSession):
    try:
        # Получаем последние показания датчиков
        latest_readings_query = sa.select(
            CurrentValues.sensors_id,
            sa.func.max(CurrentValues.time).label("latest_time")
        ).group_by(CurrentValues.sensors_id).subquery()

        latest_data_query = sa.select(
            CurrentValues,
            Sensors.sensor_name,
            ProductionLine.name.label("location_name")
        ).join(
            latest_readings_query,
            sa.and_(
                CurrentValues.sensors_id == latest_readings_query.c.sensors_id,
                CurrentValues.time == latest_readings_query.c.latest_time
            )
        ).join(
            Sensors, CurrentValues.sensors_id == Sensors.id
        ).join(
            ProductionLine, Sensors.location == ProductionLine.id
        )

        latest_data_result = await db.execute(latest_data_query)
        latest_readings = latest_data_result.fetchall()

        sensor_readings = []
        for row in latest_readings:
            sensor_readings.append({
                "sensor_id": row.CurrentValues.sensors_id,
                "sensor_name": row.sensor_name,
                "location_name": row.location_name,
                "value": float(row.CurrentValues.value),
                "unit": SENSOR_UNITS.get(row.sensor_name, ""),
                "time": row.CurrentValues.time.strftime("%Y-%m-%d %H:%M:%S") if row.CurrentValues.time else None
            })

        # Получаем последние события/оповещения
        events_query = sa.select(
            Events,
            Sensors.sensor_name,
            ProductionLine.name.label("location_name")
        ).join(
            Sensors, Events.sensors_id == Sensors.id
        ).join(
            ProductionLine, Sensors.location == ProductionLine.id
        ).order_by(
            Events.time.desc()
        ).limit(5)

        events_result = await db.execute(events_query)
        events = events_result.fetchall()

        recent_events = []
        for event in events:
            recent_events.append({
                "id": event.Events.id,
                "sensor_id": event.Events.sensors_id,
                "sensor_name": event.sensor_name,
                "description": event.Events.description,
                "location": event.location_name,
                "timestamp": event.Events.time.strftime("%Y-%m-%d %H:%M:%S") if event.Events.time else None
            })

        # Формируем данные о статусе экструдера
        extruder_status = await generate_extruder_status(db)

        return {
            "sensor_readings": sensor_readings,
            "recent_events": recent_events,
            "extruder_status": extruder_status
        }
    except Exception as e:
        logger.error(f"Ошибка при генерации данных дашборда: {e}")
        # Заворачиваем ошибку в транзакцию, чтобы не прерывать сессию
        await db.rollback()

        return {
            "error": f"Ошибка при генерации данных: {str(e)}",
            "sensor_readings": [],
            "recent_events": [],
            "extruder_status": {"status": "error", "message": f"Ошибка: {str(e)}", "metrics": {}}
        }


async def generate_extruder_status(db: AsyncSession):
    try:
        # Получаем ID местоположения
        location_query = sa.select(ProductionLine.id).where(ProductionLine.name == "Экструдер")
        location_result = await db.execute(location_query)
        location_id = location_result.scalar_one_or_none()

        if not location_id:
            return {
                "status": "unknown",
                "message": "Местоположение 'Экструдер' не найдено",
                "metrics": {}
            }

        # Запрос для подсчета событий за последние сутки
        events_count_query = sa.select(sa.func.count(Events.id)).where(
            Events.time > sa.text("NOW() - INTERVAL '1 day'"),
            sa.exists().where(
                sa.and_(
                    Sensors.id == Events.sensors_id,
                    Sensors.location == location_id
                )
            )
        )
        events_result = await db.execute(events_count_query)
        events_count = events_result.scalar() or 0

        # Получаем данные о активных датчиках экструдера
        active_sensors_query = sa.select(sa.func.count(Sensors.id)).where(
            Sensors.location == location_id,
            Sensors.active == True
        )
        active_sensors_result = await db.execute(active_sensors_query)
        active_sensors = active_sensors_result.scalar() or 0

        # Получаем данные о последних показаниях
        latest_readings_query = sa.select(
            CurrentValues
        ).join(
            Sensors, CurrentValues.sensors_id == Sensors.id
        ).where(
            Sensors.location == location_id
        ).order_by(
            CurrentValues.time.desc()
        ).limit(1)

        latest_reading_result = await db.execute(latest_readings_query)
        latest_reading = latest_reading_result.scalar_one_or_none()

        last_update = latest_reading.time if latest_reading else datetime.now()

        # Определяем статус экструдера на основе имеющихся данных
        if events_count > 5:
            status = "critical"
            status_message = "Критический: обнаружено множество оповещений"
        elif events_count > 2:
            status = "warning"
            status_message = "Внимание: обнаружены оповещения"
        elif active_sensors > 0:
            status = "normal"
            status_message = "Нормальный: экструдер работает стабильно"
        else:
            status = "unknown"
            status_message = "Неизвестно: недостаточно данных"

        # Получаем основные показатели экструдера
        metrics = {
            "active_sensors": active_sensors,
            "events_24h": events_count,
            "last_update": last_update.strftime("%Y-%m-%d %H:%M:%S") if last_update else datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S")
        }

        return {
            "status": status,
            "message": status_message,
            "metrics": metrics
        }
    except Exception as e:
        logger.error(f"Ошибка при генерации статуса экструдера: {e}")
        return {
            "status": "error",
            "message": f"Ошибка получения статуса",
            "metrics": {
                "active_sensors": 0,
                "events_24h": 0,
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }


# Функция для создания тестовых показаний датчиков
async def create_test_readings(db: AsyncSession, sensors):
    try:
        # Создаем тестовые настройки оборудования, если их нет
        for sensor in sensors:
            # Проверяем, есть ли настройки для этого датчика
            settings_query = sa.select(EquipmentSettings).where(
                EquipmentSettings.sensor_id == sensor.id
            )
            settings_result = await db.execute(settings_query)
            setting = settings_result.scalars().first()

            if not setting:
                # Создаем новую настройку в зависимости от типа датчика
                if "Температура экструдера" in sensor.sensor_name:
                    new_setting = EquipmentSettings(
                        sensor_id=sensor.id,
                        min_value=160,
                        max_value=180
                    )
                elif "Скорость протяжки" in sensor.sensor_name:
                    new_setting = EquipmentSettings(
                        sensor_id=sensor.id,
                        min_value=30,
                        max_value=40
                    )
                elif "Толщина изоляции" in sensor.sensor_name:
                    new_setting = EquipmentSettings(
                        sensor_id=sensor.id,
                        min_value=1.8,
                        max_value=2
                    )
                elif "Сечение жилы" in sensor.sensor_name:
                    new_setting = EquipmentSettings(
                        sensor_id=sensor.id,
                        min_value=49.8,
                        max_value=50.2
                    )
                else:
                    new_setting = EquipmentSettings(
                        sensor_id=sensor.id,
                        min_value=0,
                        max_value=100
                    )

                db.add(new_setting)

        await db.commit()

        # Создаем тестовые показания
        test_readings = []
        current_time = datetime.now()

        for sensor in sensors:
            # Генерируем значение в пределах для конкретного датчика
            if "Температура экструдера" in sensor.sensor_name:
                value = random.uniform(160-5, 180+5)
            elif "Скорость протяжки" in sensor.sensor_name:
                value = random.uniform(30-1, 40+1)
            elif "Толщина изоляции" in sensor.sensor_name:
                value = random.uniform(1.8-0.1, 2+0.1)
            elif "Сечение жилы" in sensor.sensor_name:
                value = random.uniform(49.8-0.1, 50.2+0.1)
            else:
                value = random.uniform(0, 100)

            new_reading = CurrentValues(
                sensors_id=sensor.id,
                value=value,
                time=current_time
            )
            test_readings.append(new_reading)

            # Создаем оповещение, если значение превышает норму
            settings_query = sa.select(EquipmentSettings).where(
                EquipmentSettings.sensor_id == sensor.id
            )
            settings_result = await db.execute(settings_query)
            setting = settings_result.scalars().first()

            if setting:
                # Проверяем условия для создания оповещения
                if value < setting.min_value:
                    message = f"Значение {round(value, 2)} ниже допустимого {setting.min_value}"

                    new_event = Events(
                        sensors_id=sensor.id,
                        description=message,
                        time=current_time,
                        users_id=1  # ID пользователя по умолчанию
                    )
                    db.add(new_event)
                elif value > setting.max_value:
                    message = f"Значение {round(value, 2)} выше допустимого {setting.max_value}"

                    new_event = Events(
                        sensors_id=sensor.id,
                        description=message,
                        time=current_time,
                        users_id=1  # ID пользователя по умолчанию
                    )
                    db.add(new_event)

        db.add_all(test_readings)
        await db.commit()

        logger.info("Успешно созданы тестовые показания датчиков")
    except Exception as e:
        await db.rollback()
        logger.error(f"Ошибка при создании тестовых показаний: {e}")


# Маршрут для WebSocket мониторинга датчиков
@app.websocket("/ws/sensors")
async def websocket_sensors(websocket: WebSocket, db: AsyncSession = Depends(get_async_session)):
    await websocket.accept()
    try:
        # Получаем информацию о датчиках
        query = sa.select(
            Sensors.id,
            Sensors.sensor_name,
            Sensors.active,
            ProductionLine.name.label("location_name")
        ).join(
            ProductionLine, Sensors.location == ProductionLine.id
        )

        result = await db.execute(query)
        sensors = result.fetchall()

        # Если датчиков нет, добавляем несколько тестовых
        if not sensors:
            logger.warning("Датчики не найдены в базе данных. Создаю тестовые датчики экструдера.")
            await create_test_sensors(db)

            # Повторяем запрос после создания тестовых датчиков
            result = await db.execute(query)
            sensors = result.fetchall()

        sensors_data = []

        if sensors:
            for sensor in sensors:
                # Получаем последние показания для датчика
                readings_query = sa.select(CurrentValues).where(
                    CurrentValues.sensors_id == sensor.id
                ).order_by(
                    CurrentValues.time.desc()
                ).limit(1)

                readings_result = await db.execute(readings_query)
                reading = readings_result.scalars().first()

                # Получаем настройки датчика
                settings_query = sa.select(EquipmentSettings).where(
                    EquipmentSettings.sensor_id == sensor.id
                )
                settings_result = await db.execute(settings_query)
                settings = settings_result.scalars().first()

                # Определяем статус
                status = "active" if sensor.active else "inactive"
                if reading and settings:
                    if reading.value < settings.min_value:
                        status = "low"
                    elif reading.value > settings.max_value:
                        status = "high"

                sensor_dict = {
                    "id": sensor.id,
                    "name": sensor.sensor_name,
                    "status": status,
                    "location": sensor.location_name,
                    "value": float(reading.value) if reading else 0,
                    "unit": SENSOR_UNITS.get(sensor.sensor_name, ""),
                    "min_value": float(settings.min_value) if settings else None,
                    "max_value": float(settings.max_value) if settings else None,
                    "last_updated": reading.time.strftime(
                        "%Y-%m-%d %H:%M:%S") if reading and reading.time else "Нет данных"
                }

                sensors_data.append(sensor_dict)

        # Отправляем данные клиенту
        await websocket.send_json({"sensors": sensors_data})

    except WebSocketDisconnect:
        logger.info("WebSocket клиент отключен от /ws/sensors")
    except Exception as e:
        logger.error(f"Ошибка при отправке данных датчиков: {e}")
        try:
            await websocket.send_json({"error": f"Ошибка получения данных датчиков: {str(e)}"})
        except:
            pass


# Функция для создания тестовых датчиков, если они отсутствуют
async def create_test_sensors(db: AsyncSession):
    try:
        # Проверяем, есть ли запись о местоположении экструдер
        location_query = sa.select(ProductionLine).where(ProductionLine.name == "экструдер")
        location_result = await db.execute(location_query)
        location = location_result.scalar_one_or_none()

        if not location:
            # Создаем местоположение экструдер
            location = ProductionLine(name="экструдер")
            db.add(location)
            await db.commit()
            logger.info("Создано местоположение 'экструдер'")

            # Перезагружаем местоположение после добавления
            location_result = await db.execute(location_query)
            location = location_result.scalar_one_or_none()

        # Создаем тестовые датчики экструдера
        test_sensors = [
            Sensors(sensor_name="Температура экструдера", location=location.id, active=True),
            Sensors(sensor_name="Скорость протяжки", location=location.id, active=True),
            Sensors(sensor_name="Толщина изоляции в экструдере", location=location.id, active=True),
            Sensors(sensor_name="Сечение жилы", location=location.id, active=True)
        ]

        db.add_all(test_sensors)
        await db.commit()

        logger.info("Успешно созданы тестовые датчики экструдера")
    except Exception as e:
        await db.rollback()
        logger.error(f"Ошибка при создании тестовых датчиков: {e}")


# Маршрут для WebSocket оповещений
@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket, db: AsyncSession = Depends(get_async_session)):
    await manager.connect(websocket, "alerts")

    # Генератор данных для оповещений
    async def generate_alerts_data():
        try:
            query = sa.select(
                Events,
                Sensors.sensor_name
            ).outerjoin(
                Sensors, Events.sensors_id == Sensors.id
            ).order_by(Events.time.desc()).limit(100)

            result = await db.execute(query)
            alerts = result.all()

            return {
                "alerts": [
                    {
                        "id": row.Events.id,
                        "time": row.Events.time.isoformat() if row.Events.time else None,
                        "description": row.Events.description,
                        "sensor_id": row.Events.sensors_id,
                        "sensor_name": row.sensor_name
                    }
                    for row in alerts
                ],
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Ошибка получения оповещений: {e}")
            return {"error": str(e)}

    # Запускаем периодическую отправку данных
    task = await manager.start_broadcast_task("alerts", 10, generate_alerts_data)

    try:
        # Ждем отключения клиента
        while True:
            data = await websocket.receive_text()
            # Если клиент отправил сообщение, можно обработать его здесь
    except WebSocketDisconnect:
        manager.disconnect(websocket, "alerts")


@app.websocket("/ws/test")
async def websocket_test(websocket: WebSocket):
    """Простой тестовый WebSocket для проверки соединения"""
    await websocket.accept()

    try:
        # Отправляем тестовое сообщение
        await websocket.send_json({"message": "Привет! WebSocket соединение работает!"})

        # Каждые 5 секунд отправляем время
        counter = 0
        while True:
            counter += 1
            await asyncio.sleep(5)
            await websocket.send_json({
                "counter": counter,
                "time": datetime.now().isoformat(),
                "message": "Это тестовое сообщение от сервера"
            })
    except WebSocketDisconnect:
        logger.info("Клиент отключился от тестового WebSocket")
    except Exception as e:
        logger.error(f"Ошибка в тестовом WebSocket: {e}")


@app.get("/test-websocket")
async def test_websocket_page(request: Request):
    return templates.TemplateResponse("test_websocket.html", {
        "request": request,
        "user": None
    })


@app.get("/api/auth-status")
async def get_auth_status(request: Request):
    token = request.cookies.get("access_token", "")
    user = getattr(request.state, "user", None)
    role = getattr(request.state, "role", None)

    return {
        "authenticated": user is not None,
        "username": user,
        "role": role,
        "has_token": bool(token),
        "token_starts_with_bearer": token.startswith("Bearer ") if token else False
    }


def handle_websocket_error(websocket, error_message):
    try:
        asyncio.create_task(websocket.send_json({
            "error": str(error_message)
        }))
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение об ошибке через WebSocket: {e}")
