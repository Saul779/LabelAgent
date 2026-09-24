"""轻量依赖注入容器：集中组装基础设施适配器与策略实现。

目的：场景实现（scenarios/）与编排层（application/）只依赖此处暴露的接口，
不直接 new 具体的 SDK 客户端，从而保证 Tag Service 部署形态切换（D007）、
多模型切换、多策略版本加载都只是“换绑定”，不改业务代码。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from label_agent.infrastructure.config_center.client import ConfigCenterClient
from label_agent.infrastructure.milvus_proxy.client import MilvusProxyClient
from label_agent.infrastructure.object_storage.client import ObjectStorageClient
from label_agent.infrastructure.tag_service.client import (
    TagServiceClient,
    tag_service_from_settings,
)
from label_agent.settings import Settings, get_settings


@dataclass
class Container:
    """请求/Job 生命周期内可复用的组件集合。"""

    settings: Settings
    config_center: ConfigCenterClient
    tag_service: TagServiceClient
    milvus_proxy: MilvusProxyClient
    object_storage: ObjectStorageClient


@lru_cache(maxsize=1)
def get_container() -> Container:
    """获取全局依赖注入容器单例。"""
    settings = get_settings()
    return Container(
        settings=settings,
        config_center=ConfigCenterClient(settings=settings),
        tag_service=tag_service_from_settings(settings),
        milvus_proxy=MilvusProxyClient(settings=settings),
        object_storage=ObjectStorageClient(settings=settings),
    )
