# Минимальный образ для деплоя на Fly.io / Render / Railway / любой Docker-хостинг
FROM python:3.12-slim
 
# libsqlite3 нужен для aiosqlite (на Pyodide отсутствует, а в обычном Python — есть)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/*
 
WORKDIR /app
 
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
 
COPY . .
 
# SQLite-файл должен переживать рестарты — монтируйте volume сюда
ENV DB_PATH=/data/food_bot.db
VOLUME ["/data"]
 
CMD ["python", "bot.py"]