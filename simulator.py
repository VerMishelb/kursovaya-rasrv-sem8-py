from config import config
import random
import time
from datetime import datetime, timedelta
import paho.mqtt.client as mqtt
import json
import logging
import argparse

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("simulator")

# Параметры MQTT по умолчанию
MQTT_BROKER = config.MQTT_BROKER
MQTT_PORT = config.MQTT_PORT
MQTT_USERNAME = config.MQTT_USERNAME
MQTT_PASSWORD = config.MQTT_PASSWORD

# Конфигурация датчиков экструдера
SENSORS = {
    # Датчики экструдера
    "temperature": {
        "id": 1, 
        "topic": "extruder/temperature", 
        "min": 160, 
        "max": 180, 
        "unit": "°C",
        "name": "Температура экструдера"
    },
    "move_speed": {
        "id": 2, 
        "topic": "extruder/move_speed", 
        "min": 30, 
        "max": 40, 
        "unit": "м/мин", 
        "name": "Скорость протяжки"
    },
    "isolation_thickness": {
        "id": 3, 
        "topic": "extruder/isolation_thickness", 
        "min": 1.8, 
        "max": 2, 
        "unit": "мм", 
        "name": "Толщина изоляции в экструдере"
    },
    "cable_core_profile": {
        "id": 4, 
        "topic": "extruder/cable_core_profile", 
        "min": 49.8, 
        "max": 50.2, 
        "unit": "мм²", 
        "name": "Сечение жилы"
    }
}


# Функция для генерации случайных значений для датчика
def generate_value(sensor, anomaly_chance=0.05):
    """Генерирует случайное значение для датчика с возможностью аномалий"""
    base_value = random.uniform(sensor["min"], sensor["max"])

    # Иногда генерируем аномальные значения для тестирования системы оповещений
    if random.random() < anomaly_chance:
        # 50% шанс превышения максимального значения
        if random.random() < 0.5:
            return sensor["max"] * (1 + random.uniform(0.1, 0.5))
        # 50% шанс значения ниже минимального
        else:
            return sensor["min"] * (1 - random.uniform(0.1, 0.5))

    return base_value


# Функция для отправки данных в MQTT
def send_sensor_data(client, sensor_name, sensor_config, anomaly_chance=0.05):
    """Отправляет сгенерированные данные датчика в MQTT топик"""
    value = generate_value(sensor_config, anomaly_chance)
    timestamp = datetime.now().isoformat()

    # Формируем сообщение
    message = {
        "sensor_id": sensor_config["id"],
        "timestamp": timestamp,
        "unit": sensor_config["unit"],
        "sensor_name": sensor_config["name"]
    }

    # Добавляем специфичное название параметра в зависимости от типа датчика
    if sensor_name == "temperature":
        message["temperature"] = round(value, 1)
    elif sensor_name == "move_speed":
        message["move_speed"] = round(value, 2)
    elif sensor_name == "isolation_thickness":
        message["isolation_thickness"] = round(value, 1)
    elif sensor_name == "cable_core_profile":
        message["cable_core_profile"] = round(value)
    else:
        message["value"] = round(value, 2)

    # Проверяем на аномалии и отправляем оповещение при необходимости
    is_anomaly = value < sensor_config["min"] or value > sensor_config["max"]
    if is_anomaly:
        alert_message = {
            "sensor_id": sensor_config["id"],
            "timestamp": timestamp,
            "sensor_name": sensor_config["name"],
            "value": round(value, 2),
            "min": sensor_config["min"],
            "max": sensor_config["max"],
            "unit": sensor_config["unit"],
            "alert_type": "value_out_of_range",
            "message": f"Значение вне допустимого диапазона: {round(value, 2)} {sensor_config['unit']}"
        }
        client.publish("extruder/alerts", json.dumps(alert_message))
        logger.warning(f"Оповещение: {json.dumps(alert_message)}")

    # Отправляем сообщение
    client.publish(sensor_config["topic"], json.dumps(message))
    logger.info(f"Отправлено: {sensor_config['topic']} - {json.dumps(message)}")


# Основная функция для запуска симулятора
def run_simulator(broker=MQTT_BROKER, port=MQTT_PORT, username=MQTT_USERNAME,
                  password=MQTT_PASSWORD, interval=5, anomaly_chance=0.05):
    """Запускает симулятор данных датчиков экструдера"""
    logger.info(f"Запуск симулятора датчиков экструдера с подключением к {broker}:{port}")

    # Настройка MQTT клиента
    client = mqtt.Client()

    # Установка аутентификации, если требуется
    if username and password:
        client.username_pw_set(username, password)

    # Подключение к брокеру
    try:
        client.connect(broker, port, 60)
        logger.info(f"Подключено к MQTT брокеру {broker}:{port}")
    except Exception as e:
        logger.error(f"Ошибка подключения к MQTT брокеру: {e}")
        return

    client.loop_start()

    try:

        # Бесконечный цикл генерации текущих данных
        while True:
            # Отправляем данные со всех датчиков
            for sensor_name, sensor_config in SENSORS.items():
                send_sensor_data(client, sensor_name, sensor_config, anomaly_chance)

            # Задержка между отправками
            time.sleep(interval)
    except KeyboardInterrupt:
        logger.info("Симулятор остановлен пользователем")
    finally:
        client.loop_stop()
        client.disconnect()
        logger.info("Отключено от MQTT брокера")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Симулятор датчиков экструдера')

    parser.add_argument('--broker', default=MQTT_BROKER, help='Адрес MQTT брокера')
    parser.add_argument('--port', type=int, default=MQTT_PORT, help='Порт MQTT брокера')
    parser.add_argument('--username', default=MQTT_USERNAME, help='Имя пользователя MQTT')
    parser.add_argument('--password', default=MQTT_PASSWORD, help='Пароль MQTT')
    parser.add_argument('--interval', type=int, default=5, help='Интервал отправки данных (сек)')
    parser.add_argument('--anomaly', type=float, default=0.05, help='Вероятность аномалий (0-1)')

    args = parser.parse_args()

    # Запуск симулятора с указанными параметрами
    run_simulator(
        broker=args.broker,
        port=args.port,
        username=args.username,
        password=args.password,
        interval=args.interval,
        anomaly_chance=args.anomaly
    )