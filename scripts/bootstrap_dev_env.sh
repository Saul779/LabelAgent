#!/usr/bin/env bash
# 初始化本地开发环境：安装依赖、拉起本地依赖容器。
set -euo pipefail

cd "$(dirname "$0")/.."

echo "[1/4] 安装 Python 依赖 (poetry install)"
poetry install

echo "[2/4] 拉起本地依赖容器 (Kafka/MinIO)"
docker compose -f deploy/docker-compose.yml up -d --wait kafka minio

echo "[3/4] Kafka/MinIO 已就绪"

echo "[4/4] 启动应用服务"
docker compose -f deploy/docker-compose.yml up -d

echo "开发环境已就绪；默认 APP_ENV=dev 可用 mock MQ，无需数据库。"
