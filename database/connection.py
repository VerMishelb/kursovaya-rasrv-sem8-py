from database.models import Role, Users, Sensors, CurrentValues, EquipmentSettings, Events, ProductionLine
from database.data_base import async_session, engine, Base
import logging

logger = logging.getLogger(__name__)


def connection(func):
    async def wrapper(*args, **kwargs):
        async with async_session() as session:
            try:
                return await func(session, *args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {func.__name__}: {e}")
                await session.rollback()
            finally:
                await session.close()
    return wrapper


async def get_async_session():
    """Получение асинхронной сессии для работы с БД"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)