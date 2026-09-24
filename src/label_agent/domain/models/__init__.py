"""核心数据契约：对应实现文档 §3。

- envelope.py   MQ 投递信封 v1/v2（§3.1）
- receipt.py    回执与 Job 四态映射（§3.2、§4.4）
- job.py        AgentJob 状态机（§4.4）
- content.py    ContentBundle 感知产物（§5.1.2）
- candidate.py  候选标签/分类（§5.1.3）
- proposal.py   SemanticProposal（LLM 语义提议，§1.3）
- evidence.py   EvidenceRef 结构化证据（§3.4）
- tag.py        Tag 生命周期与向量状态（§6.3）
- s3_result.py  ContentLabelResult（§3.3.1）
- t1_result.py  TaskDetailResult（§3.3.2）
- s1_result.py  CareerRecognitionResult（§3.3.3）
- s2_result.py  CertificateRecognitionResult（§3.3.4）
- generative_candidate.py  GeneratedCandidate（§5.3）
"""
