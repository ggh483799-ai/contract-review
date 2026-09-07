FROM python:3.11-slim

# OCR 渲染依赖的系统图形库（slim 镜像缺 libxcb/libGL 等，cv2/fitz 运行时才会炸）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

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
