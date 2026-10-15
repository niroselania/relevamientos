FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080 DATA_DIR=/data
WORKDIR /app
COPY app.py index.html app.js styles.css seed.json ./
RUN mkdir -p /data && useradd --system --uid 10001 --create-home appuser && chown -R appuser:appuser /app /data
USER appuser
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)" || exit 1
CMD ["python", "app.py"]
