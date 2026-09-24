"""生成 docs/项目介绍_初级开发者指南.md。"""
from __future__ import annotations

from pathlib import Path

INV = Path("docs/_api_inventory.txt")
OUT = Path("docs/项目介绍_初级开发者指南.md")

HEADER = r'''# LabelAgent 项目介绍（初级开发者指南）

> 本文的源码符号附录仍可用于查找类型；其中部分运行状态说明生成较早。
> 2026-08-20 的实测完成度、生产缺口、实施方案和调试步骤以
> [`项目全面分析与开发调试指南.md`](./项目全面分析与开发调试指南.md) 为准。

| 项目 | 内容 |
|------|------|
| 文档目的 | 让初级开发者完整理解架构、目录、文件职责、类/函数角色与运行流程 |
| 代码基线 | `src/label_agent/`（约 200 个 Python 模块） |
| 权威设计 | [`agent_implementation_design.md`](./agent_implementation_design.md) |
| 上手入口 | `scripts/run_s1_mvp.py` / `scripts/run_s2_mvp.py`（当前最易跑通） |

> 读完本文你应能回答：任务从哪进来、数据怎么在模块间流动、改某个功能该改哪个文件、为什么不能随便写 Tag Service。

---

## 目录

1. [五分钟搞懂项目](#1-五分钟搞懂项目)
2. [核心设计原则（务必记住）](#2-核心设计原则务必记住)
3. [总体架构与运行时流程](#3-总体架构与运行时流程)
4. [两条运行路径对比](#4-两条运行路径对比)
5. [目录设计总览](#5-目录设计总览)
6. [场景管线详解](#6-场景管线详解)
7. [关键数据对象（在流程中“传什么”）](#7-关键数据对象在流程中传什么)
8. [按包详解：文件 / 类 / 函数职责](#8-按包详解文件--类--函数职责)
9. [配置、脚本与本地运行](#9-配置脚本与本地运行)
10. [实现成熟度（哪些能跑、哪些是骨架）](#10-实现成熟度哪些能跑哪些是骨架)
11. [新人学习路径建议](#11-新人学习路径建议)
12. [附录：完整源码符号清单](#12-附录完整源码符号清单)

---

## 1. 五分钟搞懂项目

### 1.1 一句话

**LabelAgent 是一个异步 AI 打标运行时**：从消息队列（MQ）收到“请给这条内容打标签 / 提取信息”的任务，按**固定场景管线**调用 LLM 与检索，产出结构化结果，再通过回执 Topic 异步返回。

它**不是**：

- 面向用户的在线搜索/推荐同步 API
- 开放式“自己想步骤”的通用 ReAct Agent

### 1.2 业务场景一览

| 场景码 | 名字 | 做什么 | 生产状态（概念） |
|--------|------|--------|------------------|
| **S3** | 动态内容分类与标签 | 对帖子/商品等内容做分类 + 标签 | 生产路由目标场景 |
| **T1** | 任务分支信息提取 | 按业务类型提取 relationship / skill / dessert 字段 | 生产路由目标场景 |
| **S1** | 职业认证/识别 | 从证书/简历等多模态输入识别职业，并可补充技能 | 功能已实现 MVP |
| **S2** | 技能认证/识别 | 从材料中识别技能标签 | 同上 |

### 1.3 用生活类比理解分层

把一次打标想象成**快递分拣中心**：

| 角色 | 项目对应 | 干什么 |
|------|----------|--------|
| 收件台 | MQ Consumer | 收到包裹（任务）并开始处理 |
| 调度员 | Orchestrator + ScenarioRegistry | 看包裹类型（场景），交给对应流水线 |
| 流水线工人 | `scenarios/*/pipeline.py` | 按固定步骤加工 |
| 眼睛/耳朵 | `perception/` | 把 PDF/图片/文本变成可读文本 |
| 字典查询 | `retrieval/` | 从词表里找可能相关的标签 |
| 顾问（只建议） | `inference/`（LLM） | 提议“可能是什么标签”，**不直接改库** |
| 质检员 | `validation/` | Schema / 证据 / 安全检查 |
| 唯一有写库权限的人 | `resolution/TagCommitter` | 通过校验后才写 Tag Service |
| 回执窗口 | ProcessTask + Publisher | 把结果寄回给上游 |

---

## 2. 核心设计原则（务必记住）

1. **场景路由，不是通用 Agent 循环**  
   每个场景是固定阶段流水线，可预测、可审计。新增场景 = 注册新 `ScenarioHandler`，不要改 Consumer/ProcessTask 主流程。

2. **LLM 只提议，系统做决策**  
   LLM 输出语义候选（如 `SemanticProposal` / `GeneratedCandidate`），**不直接产生最终标签 ID、不执行写操作、不决定最终阈值**。

3. **写操作前置校验**  
   任何对 Tag Service / Milvus / 结果发布的写入，必须先过 `validation/`。  
   **全仓库唯一允许写 Tag Service 的组件是 `resolution.TagCommitter`。**

4. **至少一次投递 + 幂等副作用**  
   Kafka 至少一次投递 + 业务版本号，解决重复消息与乱序；不追求端到端 Exactly-Once，不落本地业务库。

5. **分类只读、标签可建**  
   分类库不能创建；标签创建必须经 Tag Service。

6. **配置驱动**  
   凡设计文档标 `[暂定]` / `[待确认]` 的规则，必须走 `configs/` 或配置中心，禁止硬编码魔法数。

7. **对外回执只有 success / fail**  
   Job 内部可有 `SUCCEEDED` / `NEED_REVIEW` / `FAILED` 等；对外映射见 `domain/models/receipt.py`。

---

## 3. 总体架构与运行时流程

### 3.1 目标生产数据流（完整形态）

```text
上游系统
   │ 投递任务到 MQ Topic
   ▼
JobWorker / IngressConsumer（解析信封、基础校验）
   │
   ▼
ProcessTask + Orchestrator.process
   │  ScenarioRegistry.resolve → 具体 ScenarioHandler.run(JobContext)
   │       │
   │       ├─ Perception（感知 → ContentBundle）
   │       ├─ Retrieval（候选召回，S3 等）
   │       ├─ LLM Propose（语义/生成式提议）
   │       ├─ Resolve / Reconcile（归一到词表 ID）
   │       ├─ PreValidate → TagCommit → PostValidate
   │       └─ 产出场景结果（S1/S2/S3/T1）
   │
   ▼
MqPublisher → MQ callback_topic（Receipt）

副路径：
  VectorWorker …… 新标签向量写入 Milvus
  ReconciliationWorker …… 对账
运维面：
  Admin API …… 健康检查 / DLQ 重放
```

### 3.2 进程入口

`label_agent.main:main`（Poetry 脚本 `label-agent`），参数 `--mode`：

| mode | 作用 | 当前实现 |
|------|------|----------|
| `api` | FastAPI 运维接口 | **已实现**（`create_app` + uvicorn） |
| `job_worker` | 消费 MQ、跑 Orchestrator、发回执 | **已实现** |
| `vector_worker` | 打标签向量 | **已实现** |
| `reconciliation_worker` | 对账 | **已实现** |

> **重要**：不要把 HTTP API 当成主业务入口。主通道是 MQ；API 是运维面。

### 3.3 Orchestrator 在流程中的角色

文件：`application/orchestrator.py`

```text
process(envelope, ctx)
  → scenario_registry.resolve(envelope) 得到 Handler
  → await handler.run(ctx)
  → 成功：组装 Receipt，返回 SUCCEEDED
  → SupersededError → SUPERSEDED
  → NeedReviewError → NEED_REVIEW
  → RetryableError → 向上抛，交给 ProcessTask 退避重试
  → NonRetryableError → FAILED
```

它**不**做具体感知/LLM 细节，只负责：选场景、跑 Handler、把异常映射成 Job 终态。

### 3.4 JobContext：单次任务的“工作记忆”

文件：`core/context.py`

- **生命周期**：仅一个 Job 从开始到结束
- **不是**：多轮对话长期记忆
- **典型字段**：`payload` → `content_bundle` → `candidates` → `semantic_proposal` → `resolved_entities` → 版本号与降级模态列表

各阶段只读写自己需要的字段，像流水线传送带上的托盘。

---

## 4. 两条运行路径对比

### 4.1 生产目标路径（MQ 全链路）

依赖：Kafka、Tag Service、Milvus、对象存储、LLM 等。  
入口：`JobWorker` → `Orchestrator` → 各场景 Handler。

### 4.2 本地 MVP 路径（新人优先）

脚本：`scripts/run_s1_mvp.py` / `run_s2_mvp.py` + `mvp_common.py`

```text
本地文件（txt/png/pdf/docx…）
  → read_input_payload 变成 payload
  → JobContext（手工构造）
  → CertificateContentLoader（感知）
  → GenerativeProposer（LLM 生成候选）
  → GenerativeCandidateReconciler + 内存词表索引（归一）
  → PII / Injection 安全过滤
  → CareerRecognitionResult / CertificateRecognitionResult JSON
```

**不依赖** MQ / Tag Commit。适合理解 S1/S2 核心算法与感知链。

运行示例：

```bash
poetry run python scripts/run_s1_mvp.py configs/fixtures/samples/career_cert_sample.txt
poetry run python scripts/run_s2_mvp.py configs/fixtures/samples/skill_cert_sample.txt
```

---

## 5. 目录设计总览

### 5.1 仓库顶层

```text
LabelAgent/
├── src/label_agent/     # 核心业务代码（本文重点）
├── configs/             # YAML 配置 + fixtures 词表/样例
├── scripts/             # 启动脚本、S1/S2 MVP CLI
├── tests/               # unit / integration / contract / e2e
├── docs/                # 需求与设计文档
├── deploy/              # docker-compose、K8s
├── dev_doc/             # 研发计划
├── pyproject.toml       # Poetry 依赖
├── Makefile             # install / test / run-* 等快捷命令
└── README.md
```

### 5.2 `src/label_agent/` 分层意图

| 包 | 一句话职责 | 允许依赖谁（直觉） |
|----|------------|--------------------|
| `domain/` | 纯数据契约与策略接口，**零外部 SDK** | 几乎只依赖标准库/pydantic |
| `core/` | 日志、tracing、异常、JobContext、DI | 基础设施细节尽量少 |
| `application/` | 编排：Orchestrator / ProcessTask / use_cases | domain + 接口 |
| `scenarios/` | 各场景 Handler + Pipeline | perception/retrieval/inference/… |
| `perception/` | 多模态 → `ContentBundle` | inference（视觉）、domain |
| `retrieval/` | 标签/分类多路召回；S1/S2 内存词表 | domain、embedding |
| `rag/` | Prompt 知识增强（默认关闭） | 与 retrieval 职责分离 |
| `inference/` | LLM Gateway、Provider、Prompt、Embedding | providers |
| `resolution/` | 实体归一；**TagCommitter 唯一写标签** | tag_service 接口 |
| `validation/` | Schema/证据/安全/规则引擎 | domain |
| `embedding/` | 标签/用户向量与可发布性 | milvus 接口 |
| `infrastructure/` | MQ、HTTP 客户端等适配器 | 外部系统 |
| `workers/` | 常驻轮询进程 | application + infrastructure |
| `api/` | 运维 HTTP | use_cases |
| `schemas/` | API DTO（≠ domain 契约） | pydantic |
| `tools/` | 只读 Tool 封装（未来 Function-Calling） | 各能力接口 |
| `utils/` | 哈希/重试等无业务语义工具 | — |

**记忆口诀**：`domain` 定契约 → `scenarios` 定步骤 → `perception/retrieval/inference` 干活 → `validation` 质检 → `resolution` 才写库 → `infrastructure` 对接外部 → `workers/api` 是进程壳。

### 5.3 与“通用 Agent 模板”的对应

| 通用模板 | 本项目 | 说明 |
|----------|--------|------|
| agents | `scenarios/` | 固定管线，不是开放循环 |
| workflows | `application/` + `*/pipeline.py` | Orchestrator + 场景内编排 |
| planners | （无） | 明确不做开放式规划 |
| tools | `tools/` | 当前管线直接调；预留 FC |
| models | `inference/providers/` | 业务只认 model alias |
| prompts | `inference/prompts/` | YAML + Jinja2 版本化 |
| rag | `rag/` | 默认关；≠ 标签召回 |
| memory | `JobContext` | 单 Job 工作记忆 |
| database | （无本地业务库） | 任务进度以 Kafka Offset 为准 |

---

## 6. 场景管线详解

### 6.1 S3 内容打标（生产主场景设计）

文件：`scenarios/s3_content/pipeline.py`

```text
ContentBundleBuilder.build
  → CandidateRetriever.retrieve          # exact/alias/bm25/vector + RRF
  → SemanticProposer.propose             # LLM 在候选约束下提议
  → EntityResolver.resolve               # 纯函数归一
  → PreValidator.validate                # 写前校验
  → TagCommitter.commit                  # 唯一写 Tag Service
  → PostValidator.validate
  → is_publishable？否 → 暂不发布（向量 PENDING）
  → ContentLabelResult
```

### 6.2 S1 职业识别（MVP 已可本地跑）

文件：`scenarios/s1_career/pipeline.py` + `perception/certificate_content_loader.py`

```text
CertificateContentLoader.build
  ├─ InputRouter.route(payload) → AttachmentRef[]
  ├─ 按 kind 分发 Text/Image/PDF/DOCX/DOC Extractor
  └─ TextNormalizer → ContentBundle.normalized_text

GenerativeProposer.propose(domain=career)
  → GenerativeCandidateReconciler.reconcile（职业词表）
  → PII/Injection 过滤
  → 对 generated_unmatched 职业再跑 skill 子流程（复用 S2 提议）
  → CareerRecognitionResult
```

**InputRouter 角色**：把乱七八糟的 payload 字段（`attachments[]` / `text` / `image_path` / `input_path`…）统一成 `AttachmentRef` 列表，避免每个 Extractor 自己猜字段名。

### 6.3 S2 技能证书识别

与 S1 对称：同一套感知，`domain=certificate`，从标准证书库匹配并输出
`CertificateRecognitionResult.certificates[].certificate_id`。MVP 不含画像回写。

### 6.4 T1 任务详情

`T1TaskDetailHandler` 先将文本和图片规整为统一内容，由 Agent 判断固定三分支，再分发到：

- `RelationshipExtractor`
- `SkillExtractor`
- `DessertExtractor`

### 6.5 场景注册

`scenarios/registry.py`：`ScenarioRegistry.register / resolve`。

---

## 7. 关键数据对象（在流程中“传什么”）

| 对象 | 定义位置 | 在流程中的角色 |
|------|----------|----------------|
| `ParsedEnvelope` | `domain/models/envelope.py` | MQ 消息解析后的统一信封 |
| `JobContext` | `core/context.py` | 单 Job 传送带 |
| `AttachmentRef` | `perception/extractors/base.py` | 一个待抽取附件（类型+路径/内联文本） |
| `ExtractionResult` | 同上 | 单个 Extractor 的文本/产物/失败信息 |
| `ContentBundle` | `domain/models/content.py` | 感知总产物（规整文本+多模态元数据） |
| `TagCandidate` 等 | `domain/models/candidate.py` | S3 召回候选 |
| `SemanticProposal` | `domain/models/proposal.py` | S3：LLM 在候选约束下的提议 |
| `GeneratedCandidate` | `domain/models/generative_candidate.py` | S1/S2：LLM 自由生成候选 |
| `ReconciledItem` | 同上 | 生成候选与词表比对归一后的中间态 |
| `CareerRecognitionResult` 等 | `domain/models/s1_result.py` 等 | 场景最终出参 |
| `Receipt` | `domain/models/receipt.py` | 对外回执 |

**证据**：`EvidenceRef` 系列（`domain/models/evidence.py`）要求标签结论能回查到原文位置/图片区域，而不是一句自由文本“因为看起来像”。

---

## 8. 按包详解：文件 / 类 / 函数职责

> 本节用“包 → 文件 → 角色”说明。**更完整的逐符号清单见第 12 节附录**（由源码 AST 自动生成，含 docstring 首句）。

### 8.1 入口与配置

| 文件 | 作用 |
|------|------|
| `main.py` | CLI：`--mode` 分发 api / 各 worker；初始化日志与 tracing |
| `settings.py` | 合并 `configs/base.yaml` + `configs/{env}.yaml` + 环境变量 → `Settings` / `get_settings()` |

### 8.2 `application/` — 编排层

| 文件 | 核心类型 | 流程角色 |
|------|----------|----------|
| `orchestrator.py` | `Orchestrator.process` | 单 Job 端到端驱动 |
| `process_task.py` | `ProcessTaskUseCase` | 执行场景并发布回执 |
| `use_cases/trigger_replay.py` | DLQ 重放 | 不得用新 task_id 绕过幂等 |

### 8.3 `core/` — 横切基础

| 文件 | 要点 |
|------|------|
| `context.py` | `JobContext` |
| `exceptions.py` | `RetryableError` / `NonRetryableError` / `NeedReviewError` / `SupersededError` / 安全与 SSRF 等 —— **决定重试还是失败** |
| `di.py` | 轻量 `Container` |
| `logging.py` / `tracing.py` / `ids.py` / `time.py` | JSON 日志、OTel、ID、UTC 毫秒 |

### 8.4 `domain/` — 契约中心

- `models/*`：信封、内容、候选、提议、证据、各场景结果、标签生命周期
- `policies/*`：置信度策略、人工审核路由、版本标记
- `confidence/default_policy.py`：MVP 临时置信度公式
- `evidence/evidence_validator.py`：证据可回查校验
- `errors.py`：领域错误（非法提议、重复 canonical 等）

### 8.5 `perception/` — 感知（新人常改区）

**S1/S2 路径（证书/简历等多格式）：**

| 文件 | 类/函数 | 角色 |
|------|---------|------|
| `input_router.py` | `InputRouter.route` / `detect_kind_from_path` | payload → 附件列表 |
| `certificate_content_loader.py` | `CertificateContentLoader.build` | 编排 Extractor → ContentBundle |
| `extractors/base.py` | `AttachmentKind` / `AttachmentRef` / `ExtractionResult` | 公共模型 |
| `extractors/text_extractor.py` | `TextExtractor.extract` | 读纯文本 |
| `extractors/docx_extractor.py` | `DocxExtractor` | DOCX |
| `extractors/doc_extractor.py` | `DocExtractor` | 老 .doc（常转 docx 路径） |
| `extractors/pdf_extractor.py` | `PdfExtractor` | PDF 文本；扫描件可降级视觉 |
| `extractors/image_vision_extractor.py` | `ImageVisionExtractor` | 图片 → LLM 描述文本 |
| `text/normalizer.py` | `TextNormalizer.normalize` | NFKC/截断/content_hash |
| `media_guard.py` | SSRF / 大小限制 | 安全护栏 |

**S3 路径：**

| 文件 | 角色 |
|------|------|
| `content_bundle_builder.py` | 多模态并行感知编排 |
| `image/` `asr/` `video/` | OCR/ASR/抽帧接口（部分仍为占位） |

### 8.6 `retrieval/` — 召回

| 文件 | 角色 |
|------|------|
| `candidate_retriever.py` | S3：多路召回 + 融合入口 |
| `matchers/exact_match.py` 等 | exact / alias / bm25 / vector |
| `fusion/rrf.py` | Reciprocal Rank Fusion |
| `generative_domain_index.py` | S1/S2 MVP：`InMemoryDomainVectorIndex` 从 YAML 建词表向量索引，`top1` 做相似度 |

### 8.7 `inference/` — LLM

| 文件 | 角色 |
|------|------|
| `llm_gateway.py` | 统一补全入口；先过注入护栏再路由 Provider |
| `model_registry.py` | alias → Provider + model_name |
| `semantic_proposer.py` | **S3**：候选约束下的语义提议 |
| `generative_proposer.py` | **S1/S2**：自由生成候选 |
| `prompts/prompt_manager.py` | 加载 YAML+Jinja2 模板 |
| `providers/openai_provider.py` | **已实现** |
| `providers/azure_*` / `local_vllm_*` | 骨架 |
| `embeddings/openai_embedding_provider.py` | 词表向量 |
| `guardrails/prompt_injection_guard.py` | Prompt 注入防护 |

模板目录：`inference/prompts/templates/{s1,s2,s3,t1}/`

### 8.8 `resolution/` — 归一与写入

| 文件 | 角色 |
|------|------|
| `entity_resolver.py` | S3 实体解析（纯函数） |
| `dedup.py` | 按 canonical 去重 |
| `tag_committer.py` | **唯一写 Tag Service** |

### 8.9 `validation/` — 质检

Pre/Post Validation、Evidence Schema、敏感词/PII/注入检测、规则引擎（按 `policy_version` 插件化）等。

### 8.10 `infrastructure/` — 外部适配

MQ（Consumer / Publisher / EnvelopeParser）、TagService（Protocol + HTTP + **Mock**）、Milvus、对象存储、配置中心。

### 8.11 `workers/` — 常驻进程

`BaseWorker.run_forever` 提供统一轮询与异常自愈；`job_worker` 直接消费 MQ 并执行，
`VectorWorker` 和向量 `ReconciliationWorker` 均已实现并完成运行入口装配。

### 8.12 `api/` — 运维面

`create_app` 挂载：health、replay；中间件：tracing、admin token。

### 8.13 `scripts/`（仓库根，非包内）

| 脚本 | 作用 |
|------|------|
| `run_s1_mvp.py` / `run_s2_mvp.py` | 本地联调主路径 |
| `mvp_common.py` | 装配 LLM/Embedding/词表/Reconciler |
| `bootstrap_dev_env.sh` | poetry + compose |
| `run_api.sh` 等 | 各 mode 包装 |
| `replay_job.py` | DLQ 重放（占位） |

---

## 9. 配置、脚本与本地运行

### 9.1 关键配置

| 路径 | 作用 |
|------|------|
| `configs/base.yaml` | 策略阈值、模型 alias、RAG 开关等默认值 |
| `configs/dev.yaml` | 开发环境覆盖；常关 OTel |
| `configs/staging.yaml` / `prod.yaml` | 环境覆盖 |
| `configs/feature_flags.yaml` | RAG、动态 Tool 等运行时开关 |
| `configs/fixtures/*_dictionary.yaml` | S1/S2 MVP 词表 |
| `.env.example` | MQ/LLM 等环境变量模板 |

### 9.2 推荐上手命令

```bash
make install
cp .env.example .env          # 至少配置 OPENAI_API_KEY / OPENAI_BASE_URL

# 当前最实用：S1/S2 MVP
poetry run python scripts/run_s1_mvp.py configs/fixtures/samples/career_cert_sample.txt

# 完整本地栈（可选）
bash scripts/bootstrap_dev_env.sh
make run-api
make test
```

---

## 10. 实现成熟度（哪些能跑、哪些是骨架）

| 能力 | 状态 |
|------|------|
| 领域契约、异常体系、设计对齐目录 | 较完整 |
| S1/S2 感知（多格式）+ 生成式提议 + 内存词表归一 | **MVP 可跑** |
| OpenAI Provider / Embedding | 已实现 |
| Mock TagService / Admin API 骨架 | 可用/可扩展 |
| Job Worker 消费 MQ 并发布回执 | **已实现** |
| Azure/vLLM Provider、OCR/ASR/视频抽帧部分接口 | **待补齐** |
| RAG | 扩展点存在，默认关闭 |

读代码时请对照 docstring：写“待补充 / NotImplemented”的就是骨架，不要误以为生产已全通。

---

## 11. 新人学习路径建议

1. 读 `README.md`（结构与设计约束）  
2. 读本文第 1～4、6.2 节  
3. **跑通** `run_s1_mvp.py`，对着打印的 JSON 理解出参字段  
4. 跟代码：`InputRouter` → `CertificateContentLoader` → `S1Pipeline` → `GenerativeProposer` → `GenerativeCandidateReconciler`  
5. 再读 `docs/agent_implementation_design.md` §2、§4、§5  
6. 最后看 `ProcessTask`、`Orchestrator`、`workers/`（可靠性与生产装配）

**改功能时的落点提示：**

- 换输入格式支持 → `perception/input_router.py` + `extractors/`
- 改职业/技能 Prompt → `inference/prompts/templates/s1|s2/`
- 改词表匹配阈值 → `configs/*.yaml` 的 `policy.retrieval_confidence`
- 改 S1 步骤顺序 → `scenarios/s1_career/pipeline.py`
- 禁止：在 Extractor / Proposer 里直接调 Tag Service 写接口

---

## 12. 附录：完整源码符号清单

以下清单由 `src/label_agent/**/*.py` 静态扫描生成。格式：

- `FILE`：模块路径与模块 docstring 首句  
- `CLASS`：类与类 docstring 首句  
- `METH` / `FUNC`：公开方法/函数（含 `__init__`；以下划线开头的私有符号默认省略）与 docstring 首句  

空模块仅标 `EMPTY`。

'''

FOOTER = r'''

---

## 相关文档索引

| 文档 | 用途 |
|------|------|
| [README.md](../README.md) | 安装、命令、设计约束摘要 |
| [agent_implementation_design.md](./agent_implementation_design.md) | 实现级 SSOT |
| [agent_architecture.md](./agent_architecture.md) | 目标架构（与推荐搜索协同） |
| [PRD.md](./PRD.md) | 产品行为验收基线 |
| [AI Agent交互协议设计.md](./AI%20Agent交互协议设计.md) | MQ 信封/回执协议 |
| [requirement_gap_analysis.md](./requirement_gap_analysis.md) | 需求差距与争议来源 |

---

*文档生成说明：第 12 节附录与仓库源码同步扫描；叙事章节描述架构与流程。若代码变更，可重新运行 `scripts/_gen_project_intro.py` 刷新附录。*
'''


def inventory_to_markdown(raw: str) -> str:
    lines_out: list[str] = []
    current_pkg = ""
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith("FILE|"):
            _, path, doc = line.split("|", 2)
            parts = path.split("/")
            pkg = parts[2] if len(parts) > 3 else "(root)"
            if pkg != current_pkg:
                current_pkg = pkg
                lines_out.append(f"\n### `{pkg}`\n")
            if doc == "EMPTY":
                lines_out.append(f"\n#### `{path}`\n\n*(空模块 / 仅包说明)*\n")
            else:
                doc_part = f" — {doc}" if doc else ""
                lines_out.append(f"\n#### `{path}`{doc_part}\n")
        elif line.startswith("  CLASS|"):
            _, name, doc = line.split("|", 2)
            lines_out.append(f"- **class `{name}`**" + (f"：{doc}" if doc else ""))
        elif line.startswith("    METH|"):
            _, name, doc = line.split("|", 2)
            lines_out.append(f"  - `{name}()`" + (f"：{doc}" if doc else ""))
        elif line.startswith("  FUNC|"):
            _, name, doc = line.split("|", 2)
            lines_out.append(f"- **function `{name}()`**" + (f"：{doc}" if doc else ""))
    return "\n".join(lines_out)


def ensure_inventory() -> str:
    """若无清单文件则先扫描源码生成。"""
    if not INV.exists():
        from scripts._gen_api_inventory import main as gen_inv  # type: ignore

        # 直接内联调用同目录脚本
        import runpy

        runpy.run_path(str(Path("scripts/_gen_api_inventory.py")), run_name="__main__")
    return INV.read_text(encoding="utf-8")


def main() -> None:
    import runpy

    runpy.run_path(str(Path("scripts/_gen_api_inventory.py")), run_name="__main__")
    inv = INV.read_text(encoding="utf-8")
    body = inventory_to_markdown(inv)
    OUT.write_text(HEADER + body + FOOTER, encoding="utf-8")
    INV.unlink(missing_ok=True)
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
