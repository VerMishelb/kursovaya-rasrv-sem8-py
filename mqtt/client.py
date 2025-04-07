import paho.mqtt.client as mqtt
import threading
import json
import logging
import time
import queue
import asyncio
from config import config

logger = logging.getLogger(__name__)

# Глобальные переменные
mqtt_client_instance = None
mqtt_connected = False
stop_flag = False
message_queue = queue.Queue()  # Очередь для хранения сообщений


# Определение соответствующего Kafka топика
def determine_kafka_topic(mqtt_topic):
    topic_mapping = {
        "extruder/temperature": "extruder_temperature",
        "extruder/move_speed": "extruder_move_speed",
        "extruder/isolation_thickness": "extruder_isolation_thickness",
        "extruder/cable_core_profile": "extruder_cable_core_profile",
        "extruder/alerts": "alerts"
    }

    # Находим подходящий ключ
    for key in topic_mapping:
        if key in mqtt_topic:
            return topic_mapping[key]

    return "default_data"


# Обработчик сообщений - только помещает в очередь
def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode()
        logger.debug(f"Получено сообщение от {msg.topic}: {payload}")
        
        # Помещаем сообщение в очередь для асинхронной обработки
        message_queue.put((msg.topic, payload))
        
    except Exception as e:
        logger.error(f"Ошибка обработки MQTT сообщения: {e}")


# Остальные обработчики MQTT
def on_connect(client, userdata, flags, rc):
    global mqtt_connected

    connection_result = {
        0: "Успешное подключение",
        1: "Неверная версия протокола",
        2: "Неверный идентификатор клиента",
        3: "Сервер недоступен",
        4: "Неверные учетные данные",
        5: "Не авторизован"
    }

    if rc == 0:
        mqtt_connected = True
        logger.info(f"Подключено к MQTT брокеру {config.MQTT_BROKER}:{config.MQTT_PORT}")

        # Подписываемся на топики экструдера
        topics = [
            "extruder/temperature/#",
            "extruder/move_speed/#",
            "extruder/isolation_thickness/#",
            "extruder/cable_core_profile/#",
            "extruder/alerts/#"
        ]

        for topic in topics:
            client.subscribe(topic)
            logger.info(f"Подписка на топик: {topic}")
    else:
        mqtt_connected = False
        logger.error(
            f"Не удалось подключиться к MQTT брокеру: {connection_result.get(rc, f'Неизвестная ошибка: {rc}')}")


def on_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False

    if rc == 0:
        logger.info("Отключено от MQTT брокера")
    else:
        logger.warning(f"Неожиданное отключение от MQTT брокера, код: {rc}")


def on_log(client, userdata, level, buf):
    logger.debug(f"MQTT лог: {buf}")


# Функция для запуска MQTT клиента в отдельном потоке
def mqtt_client_thread():
    global mqtt_client_instance, mqtt_connected, stop_flag

    # Создаем и настраиваем клиент
    client = mqtt.Client()
    mqtt_client_instance = client

    # Устанавливаем обработчики
    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = on_disconnect

    # Устанавливаем учетные данные, если указаны
    if config.MQTT_USERNAME and config.MQTT_PASSWORD:
        client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)

    # Бесконечный цикл повторных попыток подключения
    while not stop_flag:
        try:
            if not mqtt_connected:
                logger.info(f"Попытка подключения к MQTT брокеру {config.MQTT_BROKER}:{int(config.MQTT_PORT)}...")
                client.connect(config.MQTT_BROKER, int(config.MQTT_PORT), 60)

            # Запускаем цикл обработки сообщений
            client.loop_start()

            # Ожидаем, пока не будет установлен флаг остановки
            while not stop_flag:
                time.sleep(1)
                if not mqtt_connected:
                    break

            # Останавливаем цикл
            client.loop_stop()

            # Если установлен флаг остановки, выходим из основного цикла
            if stop_flag:
                break

            # Иначе ждем немного и пробуем подключиться снова
            logger.info("Переподключение к MQTT брокеру...")
            time.sleep(5)

        except Exception as e:
            logger.error(f"Ошибка MQTT клиента: {e}")
            time.sleep(5)

    # Отключаемся при выходе
    try:
        if mqtt_connected:
            client.disconnect()
            logger.info("MQTT клиент отключен")
    except Exception as e:
        logger.error(f"Ошибка при отключении MQTT клиента: {e}")


# Асинхронная функция для обработки сообщений из очереди
async def process_message_queue():
    from kafka.producer import produce_message
    from processing.data_processor import process_data
    
    while not stop_flag:
        try:
            # Проверяем очередь
            if not message_queue.empty():
                try:
                    topic, payload = message_queue.get_nowait()
                    
                    # Парсим данные
                    data = json.loads(payload)
                    
                    # Определяем топик Kafka
                    kafka_topic = determine_kafka_topic(topic)
                    
                    # Отправляем в Kafka (если доступен)
                    try:
                        await produce_message(kafka_topic, data)
                    except Exception as e:
                        logger.error(f"Ошибка отправки в Kafka: {e}")
                    
                    # Обрабатываем данные напрямую (без Kafka)
                    try:
                        await process_data(topic, data)
                    except Exception as e:
                        logger.error(f"Ошибка обработки данных: {e}")
                    
                except json.JSONDecodeError:
                    logger.error(f"Ошибка декодирования JSON: {payload}")
                except Exception as e:
                    logger.error(f"Ошибка при обработке сообщения из очереди: {e}")
            
            # Небольшая пауза для экономии ресурсов
            await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error(f"Ошибка в обработчике очереди сообщений: {e}")
            await asyncio.sleep(1)


# Асинхронная функция для запуска MQTT клиента
async def mqtt_client():
    global stop_flag

    # Сбрасываем флаг остановки
    stop_flag = False

    # Создаем и запускаем поток MQTT клиента
    thread = threading.Thread(target=mqtt_client_thread)
    thread.daemon = True
    thread.start()

    # Запускаем асинхронную обработку сообщений
    queue_processor = asyncio.create_task(process_message_queue())

    # Ждем, пока не будет установлен флаг остановки
    try:
        while not stop_flag:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        logger.info("Получен сигнал остановки MQTT клиента")
        stop_flag = True

        # Отменяем обработчик очереди
        queue_processor.cancel()
        try:
            await queue_processor
        except asyncio.CancelledError:
            pass

        # Ждем завершения потока
        if thread.is_alive():
            thread.join(timeout=5)

        raise


# Функция для остановки MQTT клиента
async def stop_mqtt_client():
    global stop_flag
    stop_flag = True
    logger.info("Отправлен запрос на остановку MQTT клиента")