# Label Agent

异步 AI Agent 运行时：消费 MQ 触发的打标/信息提取任务（动态内容分类标签 S3、商品打标 S4、
任务分支信息提取 T1，及职业认证 S1/技能认证 S2），产出结构化分类、标签与字段，通过回执 Topic 异步返回。

> **实现状态（2026-09-02）**：S4 商品打标已实现 OCR+Vision、双模型复核、0.85
> 决策、搜索词/类目建议和 MQ 业务决策映射；MVP 可用本地 xlsx 混合召回，生产可复用
> `EmbeddingProvider` 与 `MilvusProxyClient` 检索服务端类目向量库。上线前仍需联调向量命中
> metadata 契约、配置远程媒体域名并完成真实模型验收。

详细设计依据：[`docs/agent_implementation_design.md`](docs/agent_implementation_design.md)（本仓库目录结构与模块划分均以此为准，章节引用见下文）。

当前代码审计、五场景完成度、后续实现路线和新人手动调试说明见：
[`docs/项目全面分析与开发调试指南.md`](docs/项目全面分析与开发调试指南.md)。

## 项目简介

- **运行模式**：场景路由（Scenario Router）而非通用 Agent 循环——按场景选择固定管线，保证可预测性和可审计性；
- **可靠性**：JobWorker 直接消费 MQ 并执行，处理完成（或进入 DLQ）后再提交 Offset；重复投递靠业务版本号与下游幂等消化；
- **可扩展性**：多场景（Agent）注册、多模型切换、Prompt 版本管理、Tool 封装、RAG 扩展点均以可插拔接口暴露，
  变更配置即可切换实现，不需要改动核心管线代码。

## 目录结构

```text
LabelAgent/
├── src/label_agent/
│   ├── core/               # 跨模块基础能力：日志/tracing/异常/JobContext(工作记忆)/依赖注入
│   ├── domain/              # 核心数据契约（§3）与策略接口（§7.2/§7.3），零外部SDK依赖
│   │   ├── models/          # TaskEnvelope/Receipt/ContentBundle/SemanticProposal/EvidenceRef/Tag/...
│   │   ├── policies/        # ConfidencePolicy、ReviewRouter 协议 + 版本注册
│   │   ├── evidence/        # EvidenceRef 纯校验逻辑
│   │   └── confidence/      # 默认置信度公式（provisional）
│   ├── scenarios/           # 多Agent扩展点：每个场景=一个可插拔 ScenarioHandler（§2.3）
│   │   ├── s3_content/      # 动态内容分类与标签（生产路由）
│   │   ├── t1_task_detail/  # 任务分支信息提取：relationship/skill/dessert（生产路由）
│   │   ├── s1_career/       # 职业认证/识别
│   │   ├── s2_skill/        # 技能认证/识别
│   │   └── s4_product/      # 商品 OCR+Vision、L2 召回、双模型分类/复核
│   ├── application/         # 编排层：Orchestrator/ProcessTask + 对外用例(use_cases)
│   ├── perception/          # 文本/图片/视频/OCR/ASR 感知，产出 ContentBundle（含 SSRF/媒体安全护栏）
│   ├── retrieval/            # 候选召回与融合：exact/alias/bm25/vector 多路 + RRF（标签/分类结构化检索）
│   ├── rag/                  # RAG 扩展点：面向 Prompt 增强的知识检索，默认关闭，与 retrieval/ 职责分离
│   ├── inference/            # LLM Gateway、多模型注册切换（model_registry）、Prompt 版本管理（prompts/）
│   ├── tools/                 # Tool 扩展点：只读能力封装（标签查询/OCR/ASR），供未来动态工具调用复用
│   ├── resolution/            # 实体解析（纯函数）与标签写入（TagCommitter，唯一写 Tag Service 的组件）
│   ├── validation/             # Schema/证据/安全校验（MVP）+ 完整规则引擎（按 policy_version 插件化）
│   ├── embedding/              # 标签向量与生命周期一致性状态机（lifecycle_status × vector_state）
│   ├── infrastructure/         # 外部系统适配：MQ、TagService、对象存储、Milvus代理、配置中心
│   ├── workers/                 # 常驻进程：Job/Vector/Reconciliation Worker
│   ├── api/                      # 运维/管理 HTTP 接口（健康检查、DLQ 重放）
│   ├── schemas/                   # API 层请求/响应 DTO（区别于 domain/models 的核心契约）
│   ├── utils/                      # 通用无业务语义工具（哈希/重试/校验器）
│   ├── main.py                     # 进程入口，按 --mode 分发 API 与各类 Worker
│   └── settings.py                 # 配置加载：configs/base.yaml + configs/{env}.yaml + 环境变量
├── configs/                # base/dev/staging/prod.yaml、logging.yaml、feature_flags.yaml
├── tests/                  # unit / integration / contract / e2e
├── scripts/                # 本地开发、迁移、重放、字典导入等运维脚本
├── deploy/                 # docker-compose（本地/生产）、K8s manifests（base + overlays）
├── docs/                   # 需求与设计文档（PRD、架构、实现设计等，均为既有文档）
├── pyproject.toml          # Poetry 依赖管理
├── Dockerfile / Makefile
└── README.md
```

### 与通用 Agent 项目模板的对应关系

本项目按 [`docs/agent_implementation_design.md`](docs/agent_implementation_design.md) 的实际业务重新设计模块划分，
而非套用通用模板目录名。对应关系供理解迁移：

| 通用模板概念 | 本项目实际模块 | 说明 |
|---|---|---|
| `agents` 多Agent | `scenarios/`（S3/S4/T1/S1/S2） | 场景路由而非开放式 Agent 循环，每个场景是独立注册的固定管线 |
| `workflows` 流程编排 | `application/`、`scenarios/*/pipeline.py` | Orchestrator 驱动 Job 全生命周期；各场景内部阶段编排在 `pipeline.py` |
| `planners` 任务规划 | 不适用（§1 设计原则 2） | 明确不采用开放式 ReAct/多步自主规划，S1/S2 转正式实现时可在 `scenarios/` 内按需引入 |
| `tools` Tool Calling | `tools/` | 只读能力封装（标签/分类查询、OCR、ASR），当前固定管线直接调用，同时可供未来 Function-Calling 复用 |
| `models` LLM封装 | `inference/providers/`、`inference/model_registry.py` | 多供应商适配 + alias 切换，业务代码只感知 alias |
| `prompts` Prompt管理 | `inference/prompts/` | 按 `<scene>-v<N>.yaml` 版本化，结果契约中记录 `prompt_version` 以便回溯 |
| `rag` RAG扩展 | `rag/` | 面向知识库增强的检索，与 `retrieval/`（标签/分类结构化召回）职责分离，默认关闭 |
| `memory` 上下文记忆 | `core/context.py`（JobContext） | 单 Job 生命周期内的“工作记忆”，非开放式多轮对话记忆（架构上不需要长期会话记忆） |
| `services` 业务服务层 | `application/`、`resolution/`、`embedding/` | 按职责拆分为编排、实体解析写入、向量生命周期，而非单一 services 包 |
| `schemas` 请求响应模型 | `schemas/`（API层）+ `domain/models/`（核心契约） | 核心数据契约独立于 API DTO，前者是系统内跨模块契约，后者只服务运维接口 |
| `database` 数据库访问 | 不使用本地业务库 | 任务进度以 Kafka Offset 为准，标签写入走 Tag Service |
| `core` 核心能力 | `core/` | 日志/tracing/异常/JobContext/依赖注入容器 |
| `utils` 通用工具 | `utils/` | 哈希、重试装饰器、通用校验器 |

## 安装说明

前置依赖：Python 3.10、[Poetry](https://python-poetry.org/)、Docker（本地依赖容器）。

```bash
# 1. 安装依赖并配置 pre-commit
make install

# 2. 复制环境变量模板并按需修改（切勿把真实密钥写回 .env.example）
cp .env.example .env

# 3. 拉起本地依赖（Kafka/MinIO）；默认 mock MQ 可不启动容器
bash scripts/bootstrap_dev_env.sh
```

本项目不落本地业务库；任务状态以 Kafka Offset 与回执为准。

## 使用方法

```bash
# 启动运维/管理 API（健康检查等；非任务投递入口）
make run-api

# MVP：Mock MQ 入站（fixture 固定信封 → 执行场景 → 本地回执）
make run-job-worker

# 生产：消费 TagCreated 事件，写入标签向量并回写 READY
MQ_BACKEND=kafka poetry run label-agent --mode vector_worker

# 生产：补偿扫描长期 PENDING 的标签向量
poetry run label-agent --mode reconciliation_worker

# S4 商品打标 MVP：仅标题 / 标题+图片 / JSON payload
poetry run python scripts/run_s4_mvp.py --title "新鲜红富士苹果 5斤装"
poetry run python scripts/run_s4_mvp.py --title "无线蓝牙耳机" --image path/to/product.jpg
poetry run python scripts/run_s4_mvp.py path/to/payload.json --out var/s4_result.json

# MQ_BACKEND=mock|kafka；默认 mock，见 configs/base.yaml 与 .env.example

# 运行单元测试 + 契约测试（integration 需另行手动执行）
make test

# 代码检查与格式化
make lint
make format
make typecheck
```

生产向量闭环要求 Tag Service 在创建标签后发布 `tag.created`，并支持标签查询及
带 `expected_definition_version` 的向量状态回写；Milvus 代理需支持
`POST /v1/vectors/upsert`。具体事件字段与 HTTP 契约见
`docs/agent_implementation_design.md` §6.3。

生产部署参考 `deploy/k8s/`（`base` + `overlays/{staging,prod}`，通过 Kustomize 管理环境差异）；
容器镜像通过根目录 `Dockerfile` 构建，按 `--mode` 参数区分进程角色（api/各 Worker），详见 `Makefile build`。

## 关键设计约束（务必先读）

1. **写操作前置校验**：任何对 Tag Service / Milvus / 结果发布的写入，必须先通过 `validation/` 校验，
   写入只能发生在 `resolution.TagCommitter`（唯一允许写 Tag Service 的组件），不得“先创建再校验”。
2. **配置驱动**：所有标记 `[暂定]`/`[待确认]` 的规则（见设计文档 §0）必须通过 `configs/` 或
   `infrastructure/config_center` 加载，禁止写入代码常量。
3. **回执二值状态**：对外回执 `status` 只有 `success`/`fail`，Job 内部四态（`SUCCEEDED`/`NEED_REVIEW`/
   `PARTIAL_SUCCESS`/`FAILED`/`SUPERSEDED`）只用于日志与回执映射；已产出有效业务结果的 `NEED_REVIEW`/
   `PARTIAL_SUCCESS` 映射 `success`，业务状态由 `payload.decision` 表达，规则见 `domain/models/receipt.py`。

## 贡献指南

- 提交前请执行 `make lint`、`make typecheck`、`make test`，确保通过后再提交；
- Git 提交信息遵循 `[type]: [description]` 规范（见 `.cursor/rules/git.mdc`）；
- 新增场景只需注册新的 `ScenarioHandler`（`scenarios/registry.py`），不得修改 Consumer/ProcessTask 主流程。

## 许可证

内部项目，暂未开源，版权归属团队所有。
