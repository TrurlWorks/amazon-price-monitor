FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MONITOR_DATA_DIR=/app/data
WORKDIR /app
RUN groupadd --gid 10001 monitor && useradd --uid 10001 --gid monitor monitor
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY backend backend
COPY migrations migrations
COPY alembic.ini app.py pyproject.toml ./
COPY tests tests
RUN mkdir /app/data && chown monitor:monitor /app/data
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "backend.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
