"""实体解析与写入（§5.1.5、§6）：唯一允许写 Tag Service 的组件位于本模块（TagCommitter）。

EntityResolver 是纯函数，无副作用；写操作只能发生在 PRE-VALIDATION 通过之后。
"""
