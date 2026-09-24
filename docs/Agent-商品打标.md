# Agent\-商品打标

## 0. 已确认实施基线（S4）

> **MVP 实现状态（2026-08-19）**：代码已注册 `S4ProductHandler`，实现工作簿快照导入、二级叶子 exact/alias/BM25/vector + RRF Top20、标题/图片感知、模型 A/B 独立判断、0.85 决策、搜索词和候选类目建议。类目描述/正反例/关键词的 LLM 离线批量富化与持久化发布仍是生产化后续项，当前索引至少使用完整一级/二级路径名称。

以下结论于 2026-08-19 确认，优先级高于本文后续早期 Prompt 示例：

1. 商品打标为独立场景 **S4**；历史文档中曾用于用户画像的 S4 编号不再使用，用户画像仍不属于本 Agent。
2. 输入允许仅标题、仅图片或标题加图片；标题非必填，图片允许 0～5 张（典型为 3～5 张），不区分主图和详情图。标题与图片冲突时以标题为分类依据，同时记录 `modality_conflict` 并进入人工审核。
3. 首期图片格式支持 JPEG、PNG、WebP、GIF（静态首帧）；HEIC、AVIF、BMP 等格式统一转码后处理。标题和图片不得同时为空。
4. 图片采用 **OCR + Vision**，提取包装文字、品牌、型号、规格和商品主体形态；单张图片失败允许降级，所有图片均失败且无标题时返回输入不可用。
5. 一个商品只输出一个一级分类和一个二级分类；当前不考虑多主体和套装商品。允许返回 `unknown/no_match`。
6. 从二级叶子类目执行 exact/alias/BM25/vector 混合召回，RRF 融合后保留 Top 20（可配置）供模型判断；一级分类由选中二级类目的 `parent_category_id` 确定，不独立检索或生成。
7. 模型 A 从候选二级类目中选择一个或返回 `unknown`；模型 B 使用不同模型或不同模型系列独立复核。模型 B 不接收模型 A 的置信度和详细理由，降低锚定效应。
8. `confidence` 表示模型基于既定置信度规则对“商品—最终一级/二级分类路径关联度”的综合评分。两个模型同意同一二级分类时，最终分数取 `min(model_a_confidence, model_b_confidence)`；自动通过阈值为 **0.85**。
9. 两模型不一致、任一模型返回 `unknown`、父子关系非法、命中排除规则、标题图片明显冲突或关键模态严重降级时，输出 `need_manual_review=true`。
10. 类目结构化知识由 LLM 直接生成并进入分类知识库，不经过运营审核；进入索引前必须通过 JSON Schema、字段完整性、类目名称不可修改、父子关系、重复/冲突、包含/排除自洽性等机器校验。失败重试后仍不合法的类目不得发布到索引。
11. Agent 不创建正式分类；仅在确认“现有类目缺失”时生成候选分类建议并随结果返回。
12. 分类自动通过后才生成并发布商品搜索词；Agent 不负责写入搜索索引。类目级搜索词离线生成，商品级搜索词逐商品生成。
13. 最终输出必须包含类目稳定 ID、类目版本、名称、置信度、决策状态、原因码、证据、模型/Prompt 版本、可选搜索词和可选候选分类建议。

### 0.1 类目主数据

商品类目来源为：[在场电商平台商品分类信息.xlsx](./在场电商平台商品分类信息.xlsx)。当前快照包含 41 个一级类目、259 条一级/二级路径，无空行和完全重复路径。表内只有名称，没有稳定 ID 与版本字段；S4 导入流程必须为每个类目分配并持久化稳定 `category_id`，并生成 `parent_category_id`、`taxonomy_version` 和状态字段。

二级名称不能作为唯一键：`办公家具` 同时位于 `家居家具`、`电脑办公` 下，`手机配件` 同时位于 `数码电子`、`手机通讯` 下；另有 `宠物用品/宠物用品` 的父子同名路径。系统必须以 `category_id` 和完整路径区分，不能仅按名称关联。

建议内部类目结构：

```JSON
{
  "category_id": "cat-l2-...",
  "category_name": "啤酒",
  "level": 2,
  "parent_category_id": "cat-l1-...",
  "status": "active",
  "taxonomy_version": "s4-taxonomy-20260819-v1"
}
```

## 一、商品分类信息结构化

商品分类信息：[在场电商平台商品分类信息.xlsx](./在场电商平台商品分类信息.xlsx)

```Markdown
# Role
你是一名资深电商商品分类专家，同时具备商品知识库建设经验。

你的任务是：
将输入的电商商品分类信息进行结构化处理，生成适用于AI商品自动分类系统的分类知识。

# Task

根据输入的：
- 一级分类名称
- 二级分类名称

生成结构化分类信息。

目标：
帮助AI模型在用户上传商品标题和商品图片时，准确判断商品应该属于哪个分类。

# 分类原则

1. 一级分类代表商品大类。
2. 二级分类代表具体商品类别。
3. 分类描述需要体现该类别的核心定义。
4. 不允许修改输入的一级分类和二级分类名称。
5. 不新增分类。
6. 不删除分类。

# 输出字段说明

请输出JSON格式。

字段要求：

## category_level_1
一级分类名称

## category_level_2
二级分类名称

## category_description
描述该分类包含什么商品。
要求：
- 20~100字
- 使用电商行业语言
- 明确商品边界


## include_products
列举该分类常见商品。

要求：
- 5~15个
- 使用消费者常见叫法

## exclude_products
列举容易误判但不属于该分类的商品。

要求：
- 3~10个

## positive_keywords

生成商品标题中有助于判断该分类的关键词。

要求：
- 包含：
  - 商品名称关键词
  - 品牌类型关键词
  - 行业术语
  - 常见简称

数量：
10~30个

## negative_keywords

生成容易导致错误分类的关键词。

要求：
- 5~15个

## classification_rules

生成AI分类判断规则。

要求：
包含：

1. 标题判断规则
2. 图片判断规则
3. 关键特征判断规则

格式：

[
"规则1",
"规则2",
"规则3"
]

## similar_categories

生成容易混淆的其他二级分类。

格式：

[
 {
 "category":"",
 "difference":""
 }
]


要求：
至少生成1个，最多5个。

## confidence

生成分类置信度。

范围：
0-1

判断标准：

0.9-1：
商品边界明确，关键词明显

0.7-0.9：
存在少量交叉，需要结合标题和图片判断

0.5-0.7：
分类边界模糊，需要更多上下文

# 输出要求

1. 只输出JSON。
2. 不输出解释文字。
3. 保持字段完整。
4. 保证JSON格式合法。

# 输入分类：

一级分类：
{{category_level_1}}

二级分类：
{{category_level_2}}

```

## 二、生成商品分类关联搜索词

根据商品分类结构化信息生成搜索词，用于搜索引擎的分级召回

提示词：

```Python
# Role

你是一名资深电商搜索算法专家。

你的任务：

根据商品分类信息，
生成该分类对应的搜索召回词。


这些搜索词用于：

1. 用户搜索时匹配分类
2. 分类下商品召回
3. 提升搜索覆盖率


# 输入


一级分类：

{{level1_category}}


二级分类：

{{level2_category}}


分类描述：

{{category_description}}


分类包含商品：

{{include_products}}


分类关键词：

{{keywords}}



# 生成原则


## 1. 只针对二级分类生成搜索词

不要生成一级分类词。

例如：

正确：

酒水饮料 > 啤酒

生成：

啤酒
精酿
黑啤


错误：

酒水
饮料



## 2. 搜索词必须符合真实用户搜索习惯


不要生成：

行业内部术语

不要生成：

营销词


## 3. 保证分类准确性


搜索词命中后，
应该大概率属于该分类。


## 4. 避免跨分类词


例如：

啤酒分类：

不要生成：

白酒
红酒
葡萄酒

# 输出JSON

{
"category_path":"",

"exact_terms":[
],

"synonym_terms":[
],

"consumer_terms":[
],

"scene_terms":[
],

"long_tail_terms":[
],

"exclude_terms":[
],


"keyword_quality_score":0
}

# 数量要求

exact_terms:

5-10个

synonym_terms:

10-20个

consumer_terms:

5-10个

scene_terms:

5-15个

long_tail_terms:

5-15个

exclude_terms:

3-10个

# keyword_quality_score

范围：

0-1

0.9以上：

搜索覆盖全面且精准

0.7-0.9：

基本满足搜索需求

0.7以下：

存在大量无效词
```

输出结果：

```Plain Text
以酒水饮料-啤酒为例

{
"category_path":
"酒水饮料/啤酒",

"exact_terms":[//精准分类词
"啤酒",
"beer",
"麦酒"
],


"synonym_terms":[//同义词
"精酿啤酒",
"黑啤",
"白啤",
"原浆啤酒",
"生啤",
"扎啤",
"进口啤酒"
],


"consumer_terms":[//消费者口语词
"喝的啤酒",
"冰啤",
"罐装啤酒",
"瓶装啤酒"
],


"scene_terms":[//场景词
"烧烤啤酒",
"聚会啤酒",
"夜宵啤酒",
"朋友聚餐酒"
],


"long_tail_terms":[//长尾搜索词
"适合烧烤喝的啤酒",
"夏天喝什么啤酒",
"精酿啤酒推荐"
],


"exclude_terms":[//防止误召回
"白酒",
"红酒",
"葡萄酒"
]
}
```

## 三、商品打标流程：

### 输入“标题”和/或“商品图片”，去“商品分类库”中寻找最接近这个商品的分类信息，得出置信度

整体流程：

```Plain Text
Step 1 商品信息理解
        ↓
Step 2 商品特征提取
        ↓
Step 3 分类知识库召回（非LLM，可用向量检索）
        ↓
Step 4 模型A选择二级叶子类目或返回unknown
        ↓
Step 5 根据parent_category_id确定一级分类
        ↓
Step 6 模型B独立复核 + 确定性规则校验
        ↓
Step 7 输出最终分类结果
```

##### step1:商品信息理解 Prompt

输入：

- 商品标题（可选）

- 商品图片（可选，0～5张，典型3～5张）

标题和图片不得同时为空。图片先执行 OCR + Vision；标题和图片冲突时以标题为分类依据，并记录 `modality_conflict`。

输出：

结构化商品画像。

这个步骤不要分类，只负责理解商品。

提示词：

```Markdown
# Role

你是一名专业的电商商品分析专家。

你的任务是：
根据商品标题和商品图片信息，对商品进行结构化理解。

注意：
当前步骤不进行商品分类，只提取商品事实信息。


# 输入

商品标题：

{{product_title}}


商品图片：

{{product_images}}


# 分析要求


请分析：

1. 商品名称

识别商品真实名称。


2. 商品主体

判断商品是什么。


3. 商品类型

例如：

- 食品
- 饮料
- 家电
- 数码产品
- 服装
- 服务
- 虚拟商品


4. 商品用途


5. 商品关键属性

包括：

- 品牌
- 型号
- 规格
- 材质
- 功能
- 使用场景


6. 图片信息

识别：

- 商品形态
- 包装形式
- 品牌LOGO
- 明显文字
- 使用场景


# 输出JSON


{
 "product_name":"",
 
 "product_type":"",
 
 "brand":"",
 
 "attributes":[
 ],
 
 "usage":"",
 
 "image_features":[
 ],
 
 "keywords":[
 ],

 "summary":""
}
```

##### Step 2：商品特征提取 Prompt

作用：

将商品理解结果转换为适合分类检索的文本。

用于：

- embedding 

- 分类召回

提示词：

```Python
# Role

你是一名电商搜索和商品知识工程专家。

你的任务：

根据商品信息生成用于商品分类检索的核心特征。

# 输入

商品信息：

{{product_analysis}}

# 要求

提取：

1. 商品核心名称

2. 商品所属行业

3. 商品用途

4. 商品关键词

5. 商品分类相关语义

注意：

不要生成营销词。

不要添加不存在的信息。

# 输出JSON

{
 "search_text":
 "",
 
 "category_features":[
 ],
 
 "important_keywords":[
 ]
}
```

##### Step 3：分类知识库召回

作用：从二级叶子类目知识库中高召回候选分类。

流程：

商品结构化检索文本：

↓

并行执行 exact / alias / BM25 / vector

↓

RRF 融合并返回 Top 20（配置项），再交给模型 A 重排选择。

候选必须携带 `category_id`、`parent_category_id`、`category_name`、`category_description`、包含/排除规则和 `taxonomy_version`。

**召回结果示例：**

```Plain Text
[
{
"category_id":"cat-l2-headphone",
"parent_category_id":"cat-l1-digital",
"一级分类":"数码电子",
"二级分类":"耳机音响",
"taxonomy_version":"s4-taxonomy-20260819-v1"
},

{
"category_id":"cat-l2-mobile-accessory",
"parent_category_id":"cat-l1-mobile",
"一级分类":"手机通讯",
"二级分类":"手机配件",
"taxonomy_version":"s4-taxonomy-20260819-v1"
}
]      
```

##### Step 4：模型 A 二级分类判断 Prompt（核心）

从召回的二级叶子候选中选择最准确的一个，或返回 `unknown`。模型不得创建候选外分类。

提示词：

```Python
# Role

你是一名资深电商商品分类专家。

你的任务：

根据商品信息，从候选二级叶子类目中选择最准确的分类。


# 商品信息

{{product_analysis}}


# 候选二级分类


{{candidate_categories}}



# 判断原则


1. 根据商品主体和实际用途判断。

2. 不根据单个关键词判断。

3. 结合标题、OCR、Vision、分类描述、包含/排除规则判断。

4. 标题与图片冲突时以标题为分类依据，但必须输出冲突原因码。

5. 候选均不符合时必须返回 `unknown`，不得强制选择。



# 输出JSON


{
 "decision":"classified/unknown",
 "level2_category_id":"",
 "confidence":0,
 "reason":"",
 "reason_codes":[],
 "matched_features":[]
}
```

##### Step 5：确定一级分类（非 LLM）

模型 A 输出 `level2_category_id` 后，系统从同一 `taxonomy_version` 的类目快照读取该二级类目的 `parent_category_id`，得到唯一一级分类。不得再次调用模型独立生成一级分类；父级缺失或层级非法时直接进入人工审核。

##### Step 6：模型 B 独立复核 Prompt

使用第二模型复核模型 A 选中的类目。为降低锚定效应，不向模型 B 提供模型 A 的置信度和详细理由。

提示词：

```Bash
# Role

你是一名电商分类审核专家。

请审核以下分类结果是否正确。

# 商品信息

{{product_analysis}}

# 分类结果

候选分类路径：

{{selected_category_path}}

其他候选二级分类：

{{candidate_level2_categories}}

# 审核要求

检查：

1. 商品是否真的属于该分类

2. 是否存在更准确分类

3. 是否违反分类边界

4. 是否应该返回 unknown

# 输出JSON

{
"pass":true,

"decision":"classified/unknown",

"correct_category":{

"level2_category_id":""

},

"problem":"",

"confidence":0,

"reason_codes":[]
}
```

模型 A、模型 B 必须选择同一二级分类，且两者置信度均不低于 0.85；最终置信度取两者较小值。系统随后执行父子关系、候选 ID、排除规则、模态冲突和输入降级等确定性校验。

##### Step 7：最终输出 Prompt

```Bash
# Role

你是商品分类系统。


根据分类结果生成最终标准输出。



# 输入

商品：

{{product}}


分类结果：

{{classification_result}}



# 输出JSON


{
 "product_id":"",

 "scene":"S4",

 "taxonomy_version":"",

 "category":{

 "level1":{"category_id":"","name":""},
 
 "level2":{"category_id":"","name":""}

 },


 "confidence":0,


 "decision":"classified/unknown/need_review",

 "need_manual_review":false,


 "reason_codes":[],

 "reason":"",

 "evidence_refs":[],

 "search_terms":null,

 "category_suggestion":null,

 "model_runs":{
   "classifier":{},
   "reviewer":{}
 }
}
```



### 如果最终置信度大于等于 0.85，且模型 A/B 一致、确定性校验通过，将选中的“分类信息”\+“生成商品搜索词”的提示词再次交给大模型处理

Agent 只发布搜索词，不负责写入搜索引擎；`unknown` 或 `need_manual_review=true` 时不生成、不发布商品搜索词。

MQ 外层 `status` 只表示技术处理：`classified`、`unknown`、`need_review` 只要成功产出合法结果均映射为 `success`；业务方必须读取 `payload.decision`，不得把 `need_review/unknown` 当作 MQ 失败重试。只有未产出合法结果的输入、类目、模型或发布故障映射 `fail`。

“生成商品搜索词”提示词：

```YAML
# Role

你是一名资深电商搜索算法专家和商品运营专家。

你的任务是：

根据商品信息、商品图片信息以及商品分类信息，
生成用于电商搜索引擎召回的搜索词。

生成的搜索词将用于：
- 商品搜索匹配
- 搜索召回扩展
- 用户意图覆盖
- 商品推荐


# 输入信息


## 商品信息

{{product_information}}


包括：

- 商品标题
- 商品属性
- 商品图片识别结果


## 商品分类信息

一级分类：

{{level1_category}}


二级分类：

{{level2_category}}


分类知识：

{{category_knowledge}}



# 搜索词生成目标


生成用户可能搜索该商品时使用的关键词。

要求：

1. 提高商品搜索召回率。

2. 保持搜索准确性。

3. 不生成与商品无关的词。

4. 不夸大商品能力。

5. 不生成虚假属性。


# 搜索词类型


## 1. core_terms（核心商品词）

定义：

用户明确寻找该商品时使用的关键词。


要求：

- 商品名称
- 商品类别
- 常用叫法


数量：

5-10个


示例：

商品：
飞天茅台53度500ml

输出：

[
"茅台酒",
"飞天茅台",
"53度白酒",
"酱香白酒"
]


---


## 2. attribute_terms（精准属性词）


定义：

商品具有明确属性的信息。


包括：

- 品牌
- 型号
- 规格
- 材质
- 功能
- 参数
- 容量
- 颜色
- 类型


要求：

必须来源于商品真实信息。


数量：

10-20个


---


## 3. scene_terms（场景联想词）


定义：

用户根据使用场景搜索商品。


包括：

- 使用场景
- 消费场景
- 人群需求
- 节日需求


要求：

符合商品实际用途。


数量：

10-20个


---


## 4. long_tail_queries（长尾问题词）


定义：

用户自然语言搜索问题。


格式：

"什么样的XXX"
"适合XXX的XXX"
"XXX哪个好"


要求：

模拟真实用户搜索。


数量：

5-15个


---


## 5. synonym_terms（同义词）


定义：

不同用户对同一商品的表达。


要求：

生成：

- 行业俗称
- 口语表达
- 简称


数量：

5-10个


---


## 6. feature_terms（卖点特征词）


定义：

商品区别于其他商品的核心特点。


例如：

- 防水
- 轻便
- 大容量
- 低糖


要求：

必须真实。


数量：

5-15个



# 禁止生成


禁止：

1. 虚假品牌词

例如：

苹果手机不能生成：
华为手机


2. 未验证属性

例如：

普通手机不能生成：
防水手机


3. 营销夸张词

例如：

世界第一
顶级
绝对最好


4. 与商品无关搜索词


# 输出格式


严格输出JSON：


{
"core_terms":[
],

"attribute_terms":[
],

"scene_terms":[
],

"long_tail_queries":[
],

"synonym_terms":[
],

"feature_terms":[
],


"search_summary":"",

"keyword_quality_score":0
}


# keyword_quality_score


评分范围：

0-1


评分标准：

0.9以上：

搜索词覆盖全面，精准度高


0.7-0.9：

基本满足搜索需求


0.7以下：

存在大量无关词


# 输入商品：

{{product_information}}


# 输入分类：

{{category_information}}
```

输出结果要求：

```JSON
{
"core_terms":[],
"attribute_terms":[],
"scene_terms":[],
"long_tail_queries":[],
"synonym_terms":[],
"feature_terms":[]
}
```

关键词搜索权重（搜索引擎会用到）：

### 如果分类结果需要人工审核，Agent 可随结果生成候选分类建议，但不得直接创建正式分类。

首先要先判断分类置信度低的原因是不是因为分类信息不足，缺少分类信息

只有确认原因属于“现有分类缺少该商品类型”时才生成候选分类建议；商品信息不足、图片解析失败或现有类目边界不清时不得建议新增。候选建议由下游审核方决定是否创建正式分类，Agent 不执行创建操作。

根据商品信息创建候选分类信息提示词：

```YAML
# Role

你是一名资深电商类目体系专家。

你的任务：

分析无法准确分类的商品，
判断现有分类体系是否存在不足，
并提出候选的新分类方案。


注意：

你的输出不会直接修改正式分类体系。

你的任务是：
辅助运营人员发现潜在新增分类。


# 输入


## 商品信息

{{product_information}}


包括：

- 商品标题
- 商品图片分析
- 商品属性


## 当前分类体系


{{current_category_tree}}



## 当前AI分类结果


一级分类：

{{predicted_level1}}


二级分类：

{{predicted_level2}}


置信度：

{{confidence}}



# 分析任务


请判断：


## 1. 分类问题原因


只能选择：

A:
现有分类可以覆盖，只是商品信息不足


B:
现有分类存在边界不清


C:
现有分类缺少该商品类型


输出：

problem_type



---

## 2. 如果属于分类缺失


生成候选分类。


分类原则：


1. 优先复用已有一级分类。


例如：

已有：

宠物用品


新增：

宠物智能设备


不要：

智能宠物


除非确实属于新的商品领域。


2. 一级分类新增必须非常谨慎。


只有满足：

- 商品规模巨大
- 独立消费场景
- 与现有一级分类差异明显

才建议新增一级分类。


---

# 输出JSON


{
"problem_type":"",

"analysis":"",


"category_suggestion":{


"operation":
"create_subcategory/create_category/no_change",


"level1_category":
"",


"level2_category":
"",


"category_description":
"",


"include_products":[
],


"exclude_products":[
],


"keywords":[
],


"reason":
""

},


"confidence":0
}



# 创建原则


新增二级分类：

要求：

1. 名称清晰

2. 不与已有分类重复

3. 可以覆盖一类商品

4. 不是单个商品特例


禁止：

根据品牌创建分类。

例如：

错误：

苹果手机

华为手机


正确：

智能手机


禁止：

根据单个型号创建分类。


例如：

错误：

iPhone15手机

正确：

手机


# 输入开始

商品信息：

{{product_information}}

分类体系：

{{current_category_tree}}
```

## 四、S4 首期验收指标

使用覆盖易混淆类目、标题缺失、仅图片、仅标题、图片部分失败、标题图片冲突和无匹配类目的人工标注测试集，至少验证：

- 二级叶子类目 `Recall@20 >= 98%`；
- 一级分类准确率 `>= 98%`；
- 二级分类整体准确率 `>= 95%`；
- 自动通过商品准确率 `>= 98%`；
- `unknown` 商品被错误自动分类的比例 `< 2%`；
- 最终输出 JSON Schema 合法率 `100%`；
- 单张图片解析失败可降级，不能导致整单异常；
- 记录模型 A/B 一致率、人工审核率、OCR/Vision 成功率、P95 时延和单商品模型成本。

上述准确率为首期验收目标；性能与成本的绝对阈值需在压测环境结合模型选型另行冻结。
