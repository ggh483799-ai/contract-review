FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY parser/ ./parser/
COPY extractor/ ./extractor/
COPY rules/ ./rules/
COPY report/ ./report/
COPY eval/ ./eval/
COPY app.py pipeline.py storage.py ./
COPY static/ ./static/

ENV PYTHONUNBUFFERED=1

EXPOSE 8020

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8020"]
