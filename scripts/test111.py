import os
from openai import OpenAI

input_text = "衣服的质量杠杠的"

client = OpenAI(
    # 若没有配置环境变量，请用阿里云百炼API Key将下行替换为：api_key="sk-xxx",
    # 各地域的API Key不同。获取API Key：https://help.aliyun.com/zh/model-studio/get-api-key
    api_key="sk-ws-H.EDYRPHR.S9AU.MEUCIQD-0HcETUuCwL10q62430gM09DyEcfBK3iUWa3CM1_KwwIgd7mypjf7Y_uZbzGKBDld7-FL0ovKRozAQXlsJppAwoc",
    # 以下是北京地域base-url，如果使用新加坡地域的模型，需要将base_url替换为：https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
    base_url="https://llm-20ty0s7iwweycibp.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
)

completion = client.embeddings.create(
    model="text-embedding-v4",
    input=input_text
)

print(completion.model_dump_json())