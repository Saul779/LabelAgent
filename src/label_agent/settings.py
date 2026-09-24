"""应用配置加载：合并 configs/base.yaml + configs/{APP_ENV}.yaml + 环境变量。

设计约束（对应实现文档 §0 实现约束 / §10）：
- 所有 [暂定]/[待确认] 规则只允许出现在配置文件或配置中心，禁止写入代码常量；
- Settings 是唯一读取原始配置文件的入口，其余模块必须通过依赖注入获得的
  Settings/ConfigCenterClient 实例访问配置，不得直接读文件。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"


def _load_yaml_layer(env: str) -> dict[str, Any]:
    """按环境加载并合并 YAML 配置层。"""
    base = _read_yaml(CONFIG_DIR / "base.yaml")
    overlay = _read_yaml(CONFIG_DIR / f"{env}.yaml")
    return _deep_merge(base, overlay)


def _read_yaml(path: Path) -> dict[str, Any]:
    """读取单个 YAML 文件为字典。"""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """深度合并配置字典（后者覆盖前者）。"""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Settings(BaseSettings):
    """环境变量优先，其余业务/策略配置通过 `yaml_config` 暴露为字典。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="dev", alias="APP_ENV")

    mq_backend: str = Field(default="", alias="MQ_BACKEND")
    mq_bootstrap_servers: str = Field(default="mock:local", alias="MQ_BOOTSTRAP_SERVERS")
    mq_consumer_group: str = Field(default="label-agent-consumer", alias="MQ_CONSUMER_GROUP")
    mq_ingress_topic: str = Field(default="agent.task.ingress", alias="MQ_INGRESS_TOPIC")
    mq_ingress_dlq_topic: str = Field(
        default="agent.task.ingress.dlq",
        alias="MQ_INGRESS_DLQ_TOPIC",
    )
    mq_callback_topic_whitelist: str = Field(
        default="agent.task.callback",
        alias="MQ_CALLBACK_TOPIC_WHITELIST",
    )
    mq_mock_ingress_fixture: str = Field(
        default="configs/fixtures/mq_ingress_sample.json",
        alias="MQ_MOCK_INGRESS_FIXTURE",
    )
    mq_mock_replay: str = Field(default="once", alias="MQ_MOCK_REPLAY")
    mq_mock_receipt_dir: str = Field(default="var/receipts", alias="MQ_MOCK_RECEIPT_DIR")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        alias="OPENAI_BASE_URL",
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        alias="OPENAI_EMBEDDING_MODEL",
    )
    azure_openai_api_key: str | None = Field(default=None, alias="AZURE_OPENAI_API_KEY")
    azure_openai_endpoint: str | None = Field(default=None, alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_api_version: str = Field(
        default="2024-06-01",
        alias="AZURE_OPENAI_API_VERSION",
    )
    local_vllm_base_url: str = Field(
        default="http://localhost:8000/v1",
        alias="LOCAL_VLLM_BASE_URL",
    )

    tag_service_base_url: str = Field(default="http://localhost:8081", alias="TAG_SERVICE_BASE_URL")
    tag_service_timeout_ms: int = Field(default=3000, alias="TAG_SERVICE_TIMEOUT_MS")
    tag_service_auth_token: str | None = Field(default=None, alias="TAG_SERVICE_AUTH_TOKEN")

    milvus_proxy_base_url: str = Field(
        default="http://localhost:8082",
        alias="MILVUS_PROXY_BASE_URL",
    )
    milvus_proxy_timeout_ms: int = Field(default=5000, alias="MILVUS_PROXY_TIMEOUT_MS")
    vector_event_topic: str = Field(default="tag.created", alias="VECTOR_EVENT_TOPIC")
    vector_consumer_group: str = Field(
        default="label-agent-vector-worker",
        alias="VECTOR_CONSUMER_GROUP",
    )

    object_storage_endpoint: str = Field(
        default="http://localhost:9000",
        alias="OBJECT_STORAGE_ENDPOINT",
    )
    object_storage_bucket: str = Field(default="label-agent-media", alias="OBJECT_STORAGE_BUCKET")
    certificate_media_allowed_domains: str = Field(
        default="",
        alias="CERTIFICATE_MEDIA_ALLOWED_DOMAINS",
    )

    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        alias="OTEL_EXPORTER_OTLP_ENDPOINT",
    )

    @property
    def yaml_config(self) -> dict[str, Any]:
        """按当前 app_env 加载并返回合并后的 YAML 配置视图。"""
        return _load_yaml_layer(self.app_env)

    @property
    def effective_mq_backend(self) -> str:
        """返回环境变量优先、YAML 兜底的 MQ 后端。"""
        yaml_backend = str((self.yaml_config.get("mq") or {}).get("backend") or "")
        return (self.mq_backend or yaml_backend or "mock").lower()

    @property
    def certificate_allowed_domain_set(self) -> set[str]:
        """返回 S1/S2 远程证书媒体域名白名单。"""
        return {
            domain.strip().lower()
            for domain in self.certificate_media_allowed_domains.split(",")
            if domain.strip()
        }

    def validate_runtime(self) -> None:
        """校验非开发环境不得使用仅适用于本地 MVP 的后端。"""
        if self.app_env.lower() not in {"staging", "prod"}:
            return
        errors: list[str] = []
        if self.effective_mq_backend != "kafka":
            errors.append("MQ_BACKEND 必须为 kafka")
        inference = self.yaml_config.get("inference") or {}
        default_alias = str(inference.get("default_model_alias") or "")
        models = inference.get("models") or []
        default_model = next(
            (model for model in models if str(model.get("alias") or "") == default_alias),
            None,
        )
        if default_model is None:
            errors.append(f"默认模型 alias 未配置: {default_alias or '<empty>'}")
        else:
            provider = str(default_model.get("provider") or "")
            if provider == "openai" and not self.openai_api_key:
                errors.append("默认 OpenAI Provider 缺少 OPENAI_API_KEY")
            elif provider == "azure_openai" and (
                not self.azure_openai_api_key or not self.azure_openai_endpoint
            ):
                errors.append(
                    "默认 Azure OpenAI Provider 缺少 AZURE_OPENAI_API_KEY/AZURE_OPENAI_ENDPOINT"
                )
            elif provider == "local_vllm" and not self.local_vllm_base_url:
                errors.append("默认 Local vLLM Provider 缺少 LOCAL_VLLM_BASE_URL")
            elif provider not in {"openai", "azure_openai", "local_vllm"}:
                errors.append(f"默认模型 Provider 不受支持: {provider or '<empty>'}")
        if errors:
            raise RuntimeError(f"{self.app_env} 环境配置无效: {'; '.join(errors)}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取 Settings 单例（环境变量 + YAML）。"""
    return Settings()
