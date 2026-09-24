"""运行环境配置校验测试。"""

from __future__ import annotations

import pytest

from label_agent.settings import Settings


def test_dev_allows_local_backends() -> None:
    settings = Settings(
        APP_ENV="dev",
        MQ_BACKEND="mock",
    )

    settings.validate_runtime()


def test_certificate_media_domains_are_normalized() -> None:
    settings = Settings(
        CERTIFICATE_MEDIA_ALLOWED_DOMAINS=" Media.Example.com,cdn.example.com, ",
    )

    assert settings.certificate_allowed_domain_set == {
        "media.example.com",
        "cdn.example.com",
    }


def test_prod_rejects_local_backends() -> None:
    settings = Settings(
        APP_ENV="prod",
        MQ_BACKEND="mock",
    )

    with pytest.raises(RuntimeError, match="kafka"):
        settings.validate_runtime()


def test_prod_accepts_kafka() -> None:
    settings = Settings(
        APP_ENV="prod",
        MQ_BACKEND="kafka",
        OPENAI_API_KEY="test-key",
    )

    settings.validate_runtime()


def test_prod_rejects_missing_default_provider_credentials() -> None:
    settings = Settings(
        APP_ENV="prod",
        MQ_BACKEND="kafka",
        OPENAI_API_KEY="",
    )

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        settings.validate_runtime()
