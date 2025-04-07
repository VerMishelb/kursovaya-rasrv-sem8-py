import asyncio
import json
import logging
from typing import Dict, List, Set
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Словарь подключений по группам
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # Задачи для отправки данных
        self.tasks: Dict[str, asyncio.Task] = {}
        
    async def connect(self, websocket: WebSocket, group: str):
        """Подключение нового клиента"""
        await websocket.accept()
        
        if group not in self.active_connections:
            self.active_connections[group] = []
        
        self.active_connections[group].append(websocket)
        logger.info(f"Клиент подключен к группе {group}, всего подключений: {len(self.active_connections[group])}")
        
    def disconnect(self, websocket: WebSocket, group: str):
        """Отключение клиента"""
        if group in self.active_connections:
            if websocket in self.active_connections[group]:
                self.active_connections[group].remove(websocket)
                logger.info(f"Клиент отключен от группы {group}, осталось подключений: {len(self.active_connections[group])}")
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Отправка сообщения конкретному клиенту"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения: {e}")
    
    async def broadcast(self, message: dict, group: str):
        """Отправка сообщения всем подключенным клиентам группы"""
        if group not in self.active_connections:
            return
            
        disconnected = []
        for connection in self.active_connections[group]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Ошибка широковещательной отправки: {e}")
                disconnected.append(connection)
        
        # Удаление отключенных соединений
        for connection in disconnected:
            self.disconnect(connection, group)
    
    async def start_broadcast_task(self, group: str, interval: float, data_generator):
        """Запуск задачи для периодической отправки данных"""
        if group in self.tasks and not self.tasks[group].done():
            self.tasks[group].cancel()
            
        task = asyncio.create_task(self._broadcast_task(group, interval, data_generator))
        self.tasks[group] = task
        return task
        
    async def _broadcast_task(self, group: str, interval: float, data_generator):
        """Периодическая отправка данных всем клиентам группы"""
        while True:
            try:
                # Если нет подключений, просто ждем
                if group not in self.active_connections or not self.active_connections[group]:
                    await asyncio.sleep(interval)
                    continue
                
                # Получаем данные от генератора
                data = await data_generator()
                
                # Отправляем данные всем клиентам группы
                await self.broadcast(data, group)
                
                # Ждем указанный интервал
                await asyncio.sleep(interval)
                
            except asyncio.CancelledError:
                logger.info(f"Задача трансляции для группы {group} отменена")
                break
            except Exception as e:
                logger.error(f"Ошибка в задаче трансляции для группы {group}: {e}")
                await asyncio.sleep(interval)
    
    def stop_all_tasks(self):
        """Остановка всех запущенных задач"""
        for group, task in self.tasks.items():
            if not task.done():
                task.cancel()
        self.tasks.clear()

# Создаем глобальный менеджер подключений
manager = ConnectionManager() 