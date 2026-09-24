"""MQ 适配协议；具体实现和工厂应从各自子模块导入。"""

from label_agent.infrastructure.mq.protocols import MqIngressConsumer, MqPublisher

__all__ = [
    "MqIngressConsumer",
    "MqPublisher",
]
