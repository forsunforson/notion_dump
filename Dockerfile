# 使用轻量级基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装基础依赖（如果需要编译某些库才装，这里基本不需要）
# RUN apt-get update && apt-get install -y gcc && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码
COPY app/ .

# 设置环境变量（或者在 docker-compose 中指定）
ENV PYTHONUNBUFFERED=1

# 启动调度器
CMD ["python", "scheduler.py"]
