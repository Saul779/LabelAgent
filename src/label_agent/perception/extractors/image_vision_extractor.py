"""图片视觉抽取器：调用多模态 LLM 将图片转为客观文字描述。

复用 S1/S2 的 vision Prompt（如 s1-vision-v1），只描述可见信息，不做职业/技能判定。
输出文本由编排层并入 ContentBundle.normalized_text，并记录 ImageArtifact。
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path

from label_agent.core.exceptions import NonRetryableError, SsrfProtectionError
from label_agent.domain.models.content import ImageArtifact
from label_agent.inference.llm_gateway import LlmGateway
from label_agent.inference.prompts.prompt_manager import PromptManager
from label_agent.inference.providers.base import ModelCompletionRequest
from label_agent.perception.extractors.base import AttachmentRef, ExtractionResult
from label_agent.perception.media_guard import MediaGuard
from label_agent.utils.hashing import sha256_hex

logger = logging.getLogger(__name__)

_EXTRACTOR_VERSION = "v1"


class ImageVisionExtractor:
    """图片 → 文字描述抽取器。

    将本地路径 / HTTP(S) URI / data URL 解析为模型可用的 image_url，
    经 PromptManager 渲染 vision 模板后调用 LlmGateway，产出描述文本与图片产物元数据。
    """

    def __init__(
        self,
        llm_gateway: LlmGateway,
        prompt_manager: PromptManager,
        media_guard: MediaGuard | None,
        *,
        vision_prompt_version: str,
        scene: str,
    ) -> None:
        """注入 LLM 网关、Prompt 管理器、媒体护栏及视觉 Prompt 版本配置。

        vision_prompt_version / scene 共同定位 templates/<scene>/<version>.yaml。
        media_guard 为 None 时跳过远程 URI 白名单校验（仅建议测试使用）。
        """
        self._llm_gateway = llm_gateway
        self._prompt_manager = prompt_manager
        self._media_guard = media_guard
        self._vision_prompt_version = vision_prompt_version
        self._scene = scene

    async def extract(
        self, attachment: AttachmentRef, *, context_hint: str = ""
    ) -> ExtractionResult:
        """对单张图片执行视觉理解，返回描述文本与 ImageArtifact。

        context_hint 来自同请求中的补充文本（可能为空），写入 user Prompt 变量。
        解析失败或 SSRF 拒绝时返回 failed_modality=image，不抛出到编排层之外
        （除非属于编程错误）；LLM 调用异常向上抛出以便重试分类。
        """
        versions = {
            "image_vision_extractor": _EXTRACTOR_VERSION,
            "vision_prompt": self._vision_prompt_version,
        }
        try:
            image_url, image_hash, local_path = self._resolve_image(attachment.ref)
        except (NonRetryableError, SsrfProtectionError) as exc:
            logger.warning("图片引用解析失败 ref=%s err=%s", attachment.ref, exc)
            return ExtractionResult(
                failed_modality="image",
                perception_versions=versions,
                error_message=str(exc),
            )

        system_prompt, user_prompt = self._prompt_manager.render(
            scene=self._scene,
            prompt_version=self._vision_prompt_version,
            variables={"context_hint": context_hint or ""},
        )
        request = ModelCompletionRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_urls=[image_url],
            max_tokens=1024,
        )
        result = await self._llm_gateway.complete(request)
        artifact = ImageArtifact(
            asset_id=local_path.name if local_path else image_hash[:16],
            uri=str(local_path) if local_path else attachment.ref,
            image_hash=image_hash,
        )
        return ExtractionResult(
            text=result.raw_text,
            image_artifacts=[artifact],
            successful_modality="image",
            perception_versions=versions,
        )

    def _resolve_image(self, image_ref: str) -> tuple[str, str, Path | None]:
        """将本地路径/HTTP URI/data URL 解析为模型可用的 image_url 与内容哈希。

        本地文件会读入并编码为 data URL；远程 HTTP(S) 经 MediaGuard 校验后直传；
        已是 data: URL 则直接使用。无法识别时抛出 NonRetryableError。
        """
        path = Path(image_ref)
        if path.exists() and path.is_file():
            data = path.read_bytes()
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            b64 = base64.b64encode(data).decode("ascii")
            return f"data:{mime};base64,{b64}", sha256_hex(data), path

        if image_ref.startswith(("http://", "https://")):
            if self._media_guard is not None:
                self._media_guard.assert_uri_allowed(image_ref)
            return image_ref, sha256_hex(image_ref), None

        if image_ref.startswith("data:"):
            return image_ref, sha256_hex(image_ref), None

        raise NonRetryableError(f"无法解析图片引用: {image_ref}")
