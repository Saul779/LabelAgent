#!/usr/bin/env python
"""S1 职业识别 MVP 本地演示入口。

用法：
  poetry run python scripts/run_s1_mvp.py path/to/cert.txt
  poetry run python scripts/run_s1_mvp.py path/to/cert.png --out result.json
  poetry run python scripts/run_s1_mvp.py img1.png img2.png img3.png
  poetry run python scripts/run_s1_mvp.py path/to/payload.json
  poetry run python scripts/run_s1_mvp.py path/to/cert.pdf
  poetry run python scripts/run_s1_mvp.py path/to/cert.docx
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

# 保证可从仓库根目录直接运行
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
for _p in (_REPO_ROOT / "src", _SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mvp_common import (  # noqa: E402
    build_domain_index,
    build_embedding_provider,
    build_evidence_matcher,
    build_llm_gateway,
    build_media_guard,
    build_prompt_manager,
    build_text_normalizer,
    load_yaml_config,
    read_input_payloads,
    require_openai_api_key,
)

from label_agent.core.context import JobContext  # noqa: E402
from label_agent.inference.generative_proposer import GenerativeProposer  # noqa: E402
from label_agent.perception.certificate_content_loader import CertificateContentLoader  # noqa: E402
from label_agent.scenarios.s1_career.handler import S1CareerHandler  # noqa: E402
from label_agent.scenarios.s1_career.pipeline import S1Pipeline  # noqa: E402
from label_agent.validation.safety.injection_detector import InjectionDetector  # noqa: E402
from label_agent.validation.safety.pii_detector import PiiDetector  # noqa: E402


async def _run(input_paths: list[Path], out_path: Path | None) -> None:
    """装配 S1 依赖并跑通一次职业识别 MVP。"""
    yaml_config = load_yaml_config()
    api_key = require_openai_api_key()
    llm_gateway = build_llm_gateway(api_key, yaml_config)
    prompt_manager = build_prompt_manager()
    embedding = build_embedding_provider(api_key)
    career_index = await build_domain_index("career", embedding)

    content_loader = CertificateContentLoader(
        text_normalizer=build_text_normalizer(),
        media_guard=build_media_guard(),
        llm_gateway=llm_gateway,
        prompt_manager=prompt_manager,
        vision_prompt_version="s1-vision-v1",
        scene="s1",
    )
    proposer = GenerativeProposer(llm_gateway=llm_gateway, prompt_manager=prompt_manager)
    pipeline = S1Pipeline(
        content_loader=content_loader,
        generative_proposer=proposer,
        matcher=build_evidence_matcher(
            "career", career_index, llm_gateway, prompt_manager, yaml_config
        ),
        pii_detector=PiiDetector(),
        injection_detector=InjectionDetector(),
        prompt_version=str(
            ((yaml_config.get("inference") or {}).get("prompt_versions") or {}).get("s1") or "s1-v2"
        ),
        dictionary_snapshot_version=career_index.dictionary_snapshot_version,
    )
    handler = S1CareerHandler(pipeline)

    payload = read_input_payloads(input_paths)
    ctx = JobContext(
        job_id=f"job-{uuid.uuid4().hex[:10]}",
        task_id=f"task-{uuid.uuid4().hex[:10]}",
        scene="S1",
        biz_id=str(payload.get("biz_id") or input_paths[0].stem),
        payload=payload,
    )
    result = await handler.run(ctx)
    output = result.model_dump()
    text = json.dumps(output, ensure_ascii=False, indent=2)
    print(text)
    if out_path:
        out_path.write_text(text, encoding="utf-8")


def main() -> None:
    """S1 MVP CLI 入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_paths",
        nargs="+",
        type=Path,
        help="一个或多个文本/图片/PDF/DOCX；多文件将作为 attachments 合并识别",
    )
    parser.add_argument("--out", type=Path, default=None, help="可选：结果 JSON 落盘路径")
    args = parser.parse_args()
    missing = [str(path) for path in args.input_paths if not path.exists()]
    if missing:
        raise SystemExit("输入不存在: " + "; ".join(missing))
    asyncio.run(_run(args.input_paths, args.out))


if __name__ == "__main__":
    main()
