# 问题一：环境配置
1、应该严格区分开发环境、测试环境、生产环境，目前大多使用统一配置  
**部分采纳**：已用 `APP_ENV` + `configs/{dev,staging,prod}.yaml` + K8s overlay 分层；`staging`/`prod` 启动时 `validate_runtime()` 禁止 mock MQ。未单独拆 `test` 环境（pytest 复用 `dev` + fixture）；业务策略仍集中在 `base.yaml`，环境文件只覆盖差异，避免三份配置分叉。

2、即使是开发环境，也应该使用Kafka模拟发送消息，而不是通过本地的方式  
**部分采纳**：`deploy/docker-compose.yml` 与 `REAL_INFRA_TEST=1` 联调已走真实 Kafka。默认 `APP_ENV=dev` 仍用 mock fixture，方便单测和无中间件的本地启动；强制开发一律 Kafka 会抬高日常开发门槛。

3、开发、测试、生产环境，应该都是用psql，而不是sqlite，否则容易出现分布式相关问题  
**已采纳（调整方案）**：已去除本地业务库（不再使用 SQLite/PostgreSQL 存 Inbox/Job/Outbox）。任务进度以 Kafka Offset 为准，标签等副作用写入外部 Tag Service。多实例互斥改由 Kafka 分区所有权承担。

4、大模型相关配置，缺少base_url，以及如何注入api_key，同时供应商与模型不匹配  
**已优化**：`Settings` 已建模 `OPENAI_BASE_URL`/`OPENAI_API_KEY` 及 Azure/vLLM 凭据；`inference_factory` 按 yaml 的 `provider` 装配对应 Provider，默认模型凭据不齐会启动失败。

# 问题二：代码规范
1、为了代码稳定可控，可以为每个文件添加测试，至少是if __name__ == '__main__'这样的简单自测脚本  
**未采纳**：用 `tests/` 下 pytest（unit/integration/contract）替代每文件 `__main__`。后者无法进 CI、会污染生产模块，也难覆盖异步 Worker。关键路径已有测试，不追求一文件一脚本。

# 问题三：MQ
1、有没有必要设计优先队列？  
**未采纳（暂缓）**：协议信封保留 `priority` 字段，消费仍按 Kafka/fixture 到达顺序。当前场景无 SLA 分级，优先队列会增加饥饿与对账复杂度，等业务明确优先级后再做。

2、为什么不是job直接消费MQ，而是要通过SQL转一层，感觉非常冗余  
如果要转一层，为什么不用同步，还要用MQ？  
**已采纳**：已拆除 Inbox/Job/Outbox 本地库。`job_worker` 直接消费入站 Topic，执行 Orchestrator 后发布回执，再提交 Offset。同步 HTTP 仍不满足上游异步回执协议，因此保留 MQ。可重试错误在进程内退避；毒消息进 DLQ。下游须按 `event_id`/`data_version` 消化重复投递。

3、kafka的默认单条消息上限是1MB，outbox内容有没有可能超过？超过应该会无限重试  
理论上，outbox应该有一个重试限制，比如5次，超过后有对应的处理策略  
**已优化**：回执 payload > 900KB 改为精简失败回执发出；发布失败最多 5 次指数退避，超限不提交 Offset 以便重启后重试，不再无限打超大消息。

# 问题四：job_id
1、看有没有必要用来查任务进度，要的话MQ处理、进度存储等都还要设计  
**已调整**：去掉本地 Job 表后不再提供 `GET /jobs/{job_id}`。`job_id` 仍写入回执，供日志与 NEED_REVIEW 关联；主完成通知仍是 MQ 回执。

2、event_id、task_id、job_id有点混淆，看着job_id知识内部使用的，感觉使用前端传过来的id来做交互更为合适  
如果不改，应该有接口用 event_id 反查 task_id  
**部分采纳**：三个 ID 职责不同，未合并为前端传入 ID。`event_id` 是幂等键，`task_id` 是协议任务号，`job_id` 是单次执行追踪号。已取消按 event_id 反查接口（无本地存储）。

# 问题五：业务调用层级
1、目前看上去ScenarioRouter、ScenarioRegistry存在过度封装
**部分采纳**：代码中已无独立 `ScenarioRouter`，`Orchestrator` 直接调用 `ScenarioRegistry.resolve()`。Registry 保留：新场景只需 `register()`，不必改编排层。内部已是 `dict[scene, handler]` 的 O(1) 查找，与问题六建议等价；再拆掉会让 Orchestrator 硬编码全部 Handler。
```
Orchestrator
├─ ScenarioRegistry
│  ├─ S1CareerHandler
│  │  └─ S1Pipeline
│  │     ├─ CertificateContentLoader
│  │     ├─ GenerativeProposer
│  │     ├─ EvidenceCandidateMatcher
│  │     ├─ PiiDetector
│  │     └─ InjectionDetector
│  │
│  ├─ S2SkillHandler
│  │  └─ S2Pipeline
│  │     ├─ CertificateContentLoader
│  │     ├─ GenerativeProposer
│  │     ├─ EvidenceCandidateMatcher
│  │     ├─ PiiDetector
│  │     └─ InjectionDetector
│  │
│  ├─ S3ContentHandler
│  │  └─ S3Pipeline
│  │     ├─ ContentBundleBuilder
│  │     ├─ CandidateRetriever
│  │     ├─ SemanticProposer
│  │     ├─ EntityResolver
│  │     ├─ PreValidator
│  │     ├─ TagCommitter
│  │     └─ PostValidator
│  │
│  ├─ S4ProductHandler
│  │  └─ S4ProductPipeline
│  │     ├─ ProductPerceptionService
│  │     ├─ ProductCategoryRetriever
│  │     ├─ ProductLabelingInference
│  │     └─ ProductTaxonomy
│  │
│  └─ T1TaskDetailHandler
│     ├─ T1ContentLoader
│     ├─ T1TaskDetailInference
│     └─ ExtractorRegistry
│        ├─ RelationshipExtractor
│        ├─ SkillExtractor
│        └─ DessertExtractor
│
└─ 业务处理完成后的统一收口
   ├─ build_receipt
   └─ MqPublisher.publish
```

# 问题六：job
1、route可以直接使用dict，更快  
**已优化**：`ScenarioRegistry._handlers` 即按 scene 的 dict，`resolve()` 为 O(1) 查找，效果等同下方示例。
```
handlers = {
    "S1": s1_handler,
    "S2": s2_handler,
    "S3": s3_handler,
    "S4": s4_handler,
    "T1": t1_handler,
}

handler = handlers[envelope.v2.scene]
```
