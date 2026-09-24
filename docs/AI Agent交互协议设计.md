# AI Agent交互协议设计

## 处理任务投递协议设计（MQ）

|字段|类型|说明|值示例|
|---|---|---|---|
|task\_id|String|任务唯一标识，用于追踪|1|
|task\_type|String|任务类型：mark\_tag|mark\_tag|
|payload\_type|String|数据类型：product|product|
|payload|JSON|具体内容：商品ID/用户ID/内容数据|具体内容设计|
|priority|Int|优先级：1紧急 2普通 3低|1|
|timestamp|Long|投递时间戳||
|callback\_topic|String|处理完后回执的Topic||

## AI Agent任务处理回执（MQ）

|字段|类型|说明|值示例|
|---|---|---|---|
|task\_id|String|关联原任务ID|1|
|task\_type|String|任务类型|mark\_tag|
|payload\_type|String|数据类型|product|
|status|String|success / fail|fail|
|message|String|如果失败，失败原因|大模型余额不足|
|payload|JSON|附加信息|具体内容设计|
|process\_time|Long|处理耗时ms||
|timestamp|Long|完成时间戳||





