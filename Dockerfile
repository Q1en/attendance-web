# 使用官方 Python 运行时作为父镜像
FROM python:3.10-slim

# 在容器中设置工作目录
WORKDIR /app

# 将 requirements.txt 文件复制到容器的 /app 目录
COPY requirements.txt .

# 安装 requirements.txt 中指定的所有必需包
# --no-cache-dir 减小镜像大小
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 将应用程序的其余代码复制到容器的 /app 目录
COPY . .

# 使容器的 5000 端口可供外部访问
EXPOSE 5000

# 为 Flask 定义环境变量 (可选, 也可以在 docker-compose.yml 中设置)
ENV FLASK_APP=app.py
# 设置为生产模式
ENV FLASK_ENV=production 
# 推荐: 通过 docker-compose.yml 中的环境变量设置 SECRET_KEY
# ENV FLASK_SECRET_KEY='your-production-secret-key'

# 使用 Gunicorn WSGI 服务器运行应用的命令
# 绑定到 0.0.0.0 以接受来自任何 IP 的连接
# 使用多个 worker 以获得更好的并发性 (根据资源进行调整)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "app:app"]