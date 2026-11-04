FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home vektra && mkdir /data && chown vektra /data
COPY --chown=vektra:vektra . .
USER vektra
ENV DATABASE_PATH=/data/vektra.sqlite3 PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 30 wsgi:app"]
