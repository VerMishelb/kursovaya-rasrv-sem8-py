import json
import asyncio
from aiokafka import AIOKafkaProducer
from config import config
import logging

logger = logging.getLogger(__name__)

# Глобальная переменная для продюсера
_producer = None

async def get_producer():
    """Создает и возвращает экземпляр Kafka продюсера"""
    global _producer
    if _producer is None:
        _producer = AIOKafkaProducer(
            bootstrap_servers=config.KAFKA_BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        await _producer.start()
        logger.info(f"Kafka продюсер подключен к {config.KAFKA_BOOTSTRAP_SERVERS}")
    return _producer

async def produce_message(topic, data):
    """Отправляет сообщение в Kafka топик"""
    try:
        producer = await get_producer()
        await producer.send_and_wait(topic, data)
        logger.debug(f"Сообщение отправлено в Kafka топик {topic}: {data}")
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения в Kafka: {e}")

async def close_producer():
    """Закрывает соединение с Kafka продюсером"""
    global _producer
    if _producer:
        await _producer.stop()
        _producer = None
        logger.info("Kafka продюсер отключен")