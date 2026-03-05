FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libreoffice \
    fontconfig \
    fonts-noto-cjk \
    fonts-dejavu \
    libglib2.0-0 \
    libxext6 \
    libxrender1 \
    libsm6 \
    libice6 \
  && rm -rf /var/lib/apt/lists/*

# 先装 Python 依赖（利用缓存）
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# 拷贝代码
COPY app /app/app
COPY scripts /app/scripts
COPY README.md /app/README.md
COPY .env.example /app/.env.example

EXPOSE 6006

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "6006"]
