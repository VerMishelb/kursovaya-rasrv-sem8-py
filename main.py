import asyncio
import logging
from mqtt.client import mqtt_client
from kafka.consumer import start_consumers
from kafka.producer import close_producer
from database.connection import Base, engine
import uvicorn
from web.app import app


logger = logging.getLogger(__name__)


async def startup():
    """Запуск всех компонентов системы"""
    try:
        # Запуск MQTT клиента
        mqtt_task = asyncio.create_task(mqtt_client())

        # Запуск Kafka консьюмеров
        consumer_task = await start_consumers()

        # Запуск веб-сервера
        web_server = uvicorn.Server(
            uvicorn.Config(
                app=app,
                host="0.0.0.0",
                port=8000,
                reload=False
            )
        )
        web_task = asyncio.create_task(web_server.serve())

        # Ожидаем завершения всех задач
        await asyncio.gather(mqtt_task, consumer_task, web_task)

    except Exception as e:
        logger.error(f"Ошибка запуска системы: {e}")
    finally:
        # Закрываем соединения при завершении
        await close_producer()


async def shutdown():
    """Корректное завершение работы системы"""
    global tasks
    
    # Отменяем все задачи
    for task in tasks:
        if not task.done():
            task.cancel()
    
    # Останавливаем WebSocket задачи
    from web.websockets import manager
    manager.stop_all_tasks()
    
    # Останавливаем MQTT клиент
    from mqtt.client import stop_mqtt_client
    await stop_mqtt_client()
    
    # Закрываем Kafka продюсер
    await close_producer()
    
    logger.info("Система остановлена")


if __name__ == "__main__":
    try:
        # Запуск основного цикла
        asyncio.run(startup())
    except KeyboardInterrupt:
        logger.info("Получен сигнал завершения работы")
        asyncio.run(shutdown())
    except Exception as e:
        logger.critical(f"Неожиданная ошибка: {e}")