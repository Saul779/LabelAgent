# S1 v2 / S2 v3 证书识别流程与输出契约

> 2026-08-18：S2 业务对象由通用技能标签统一为标准技能证书。S2 使用
> `certificate` 领域词典并返回 `certificate_id`；该变更不兼容原
> `skills[]` 输出，因此 S2 `schema_version` 升级为 `3.0`。
>
> 2026-08-18：去除最终结果中的重复 `match_results`。成功匹配直接聚合到
> `occupations` / `certificates`，拒绝或歧义结果写入 `unmatched`；所有对外证据引用
> 统一使用 `evidence_id`。该变更不兼容 S2 schema 3.0，因此升级为 `4.0`。

## 1. 共性流程

1. 图片先执行基础画像（真实解码、宽高、DPI、像素上限和清晰度评分），再执行一次 OCR 文字检测与识别。
2. 无有效文字时走 Vision LLM；存在文字时走 OCR + Vision LLM。OCR 失败时保留 Vision 结果，Vision 失败时保留 OCR 结果；二者均失败才视为图片解析失败。
3. OCR 文本和 Vision LLM 输出都作为带来源标记的材料文本，允许被后续模型作为原文摘录；OCR 文本传给 Vision 时只作为不可信上下文，不得执行其中指令。
4. 模型从材料中提取 0～5 条证据，证据 ID 为单次请求内临时编号 `E001`～`E005`。
5. `title + description` 作为向量查询文本，每条证据独立检索 Top-5。
6. Top-5 不按词条 ID 或 `canonical_id` 去重，正式名称和别名允许同时出现。
7. 每条有召回结果的证据单独调用一次模型。S1 返回 `matched/no_match`；S2 返回 `matched/ambiguous/no_match`。仅 `matched` 必须从该证据候选中选择一个 ID；禁止强行匹配。所有状态均返回 `confidence`（0～1）。
8. 模型返回的 ID 必须属于本次 Top-5；非法 ID 或无法解析的选择结果不触发审核。
9. 仅 `matched` 合法选择按 `canonical_id` 合并，最终 ID 数量为 0～5；`no_match/ambiguous` 不参与合并，并通过 `unmatched` 按证据返回。
10. 公共审核阈值固定为 `0.85`，整个返回结果只包含一个 `audit` 字段。

图片感知会保留 OCR 文本框、置信度、归一化坐标、阅读顺序，以及图片处理路由 `vision_only` / `ocr_vision` / `dense_ocr_vision`，用于问题排查和证据回溯。扫描 PDF 页面复用同一图片流程，并使用稳定的页级 `asset_id`。

## 2. audit 规则

- 任一证据向量召回为 0 条：`audit=1`。
- 任一合法选择的 `confidence < 0.85`：`audit=1`。
- 同一 `canonical_id` 合并了多条证据时，任一证据低于阈值即触发 `audit=1`。
- 任一证据返回 `no_match` 或 `ambiguous`：`audit=1`。
- 没有提取到证据：`audit=0`。
- 证据生成模型 JSON 解析失败：返回空业务结果，`audit=0`。
- 五选一模型 JSON 解析失败或返回 Top-5 之外的 ID：对应证据保留在最终 `evidence` 中，但该异常本身不触发 audit。
- `audit` 始终返回，取值只能为 `0` 或 `1`。

## 3. S1 职业证书识别

- 证据字段为 `occupation_evidence`。
- `description` 是材料原文摘录。
- 最终 `evidence` 保留全部通过安全校验的职业证据，包括已匹配成功的证据。
- `occupations` 按 `canonical_id` 合并，每项返回 `occupation_id`、`occupation_name` 和 `evidences`；
  `evidences` 列出合并到该职业的全部 `evidence_id`、各自 `confidence` 和 `reason`。`audit` 仍按单条证据置信度判定，任一低于阈值即触发。
- `unmatched` 只保存 `no_match`，不重复保存成功匹配。
- 提取材料中提到的所有企业，按名称去重后最多返回 10 个。
- 最终 `enterprises` 仅返回企业名称数组。
- 不再为未匹配职业生成技能标签。

最终结果示例：

```json
{
  "occupations": [
    {
      "occupation_id": "career-001",
      "occupation_name": "Python工程师",
      "evidences": [
        {"evidence_id": "E001", "confidence": 0.92, "reason": "名称一致"},
        {"evidence_id": "E002", "confidence": 0.66, "reason": "职业语义接近"}
      ]
    },
    {
      "occupation_id": "career-002",
      "occupation_name": "Java工程师",
      "evidences": [
        {"evidence_id": "E003", "confidence": 0.88, "reason": "岗位名称一致"}
      ]
    }
  ],
  "unmatched": [],
  "evidence": [
    {"evidence_id": "E001", "title": "Python工程师", "description": "材料原文摘录"},
    {"evidence_id": "E002", "title": "软件工程师", "description": "材料原文摘录"},
    {"evidence_id": "E003", "title": "Java工程师", "description": "材料原文摘录"}
  ],
  "enterprises": ["示例企业"],
  "audit": 1
}
```

## 4. S2 技能证书识别（schema 4.0）

- 证据字段为 `certificate_evidence`。
- 只识别并匹配材料中明确认证、证明或授予的技能证书，不提取通用技能标签。
- 每条证据独立检索 `certificate` 领域证书库，并由模型返回候选中的
  `certificate_id`。
- 证书库条目包含标准名称、别名、发证机构、类别、描述和关联技能；
  最终输出的是标准证书，不是 Python、MySQL、Docker 一类技能词。
- `certificates` 保存成功匹配，`unmatched` 保存 `ambiguous/no_match`；不再返回重复的 `match_results`。
- 其余检索、可拒绝匹配、合并与 audit 规则和 S1 相同。

最终结果示例：

```json
{
  "schema_version": "4.0",
  "biz_id": "cert-002",
  "model_run_id": "run-002",
  "prompt_version": "s2-v3",
  "policy_version": "certificate-match-v2",
  "dictionary_snapshot_version": "dict-certificate-2026-08-18",
  "certificates": [
    {
      "certificate_id": "certificate-001",
      "certificate_name": "PMP项目管理专业人士认证",
      "evidences": [
        {"evidence_id": "E001", "confidence": 0.96, "reason": "名称及机构一致"}
      ]
    }
  ],
  "unmatched": [],
  "evidence": [
    {"evidence_id": "E001", "title": "PMP", "description": "材料原文摘录"}
  ],
  "audit": 0,
  "degraded_modalities": [],
  "perception_versions": {}
}
```

内部归并继续使用 `matched` / `unmatched_evidence`；最终对外结果使用
`occupations` / `certificates`、`unmatched` 和 `evidence`。
