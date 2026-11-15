FROM python:3.12.8-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home metis
COPY metis ./metis
COPY web ./web
COPY scripts ./scripts
RUN mkdir /data && chown metis:metis /data
USER metis
ENV METIS_SQLITE_PATH=/data/fixture.sqlite
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/')"
CMD ["uvicorn","metis.main:app","--host","0.0.0.0","--port","8000","--workers","1"]
