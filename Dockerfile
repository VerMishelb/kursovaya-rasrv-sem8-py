FROM python:3.10-slim

WORKDIR /app

# Установка зависимостей системы
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Копирование файлов проекта
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Создание пользователя без прав root
RUN adduser --disabled-password --gecos '' appuser
USER appuser

# Запуск приложения
CMD ["python", "main.py"]