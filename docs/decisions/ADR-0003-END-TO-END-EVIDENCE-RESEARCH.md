# ADR-0003 — 自然语言研究闭环，而非 CLI 组件陈列

- 日期：2026-10-09
- 状态：Implemented, offline-contract verified; live model/deployment validation pending
- 替代：ADR-0002 中将生成式综合推迟至未来阶段的表述

## 问题：错把可测切片当成用户成果

曾交付 `search`、`decide`、`export` 三个独立原语，却没有提供完整的“提问→检索→判断→生成→引用交付”。这是一种交付指标的 Goodhart 式偏移：CLI 通过测试，却不是研究助手。

## 新的行为合同

```text
xc ask "我想了解 Opus 5.5"
xc research "Jev" --out notes/jev

自然语言意图识别
  → 本地 SQLite FTS5 / D1 bookmark_fts + 权威书签词法兜底
  → Clef-flash / Clef / Jev 自动逐条评估相关性与广告属性
  → Workers AI LLM / 本地直连的 DeepSeek 生成证据综述
  → 终端回答，或 report.md + sources.jsonl + posts/*.md + decisions.jsonl
```

端到端编排共享 `src/research.py`；`src/research_cloud.py` 与 `src/research_direct.py` 只提供模型 IO 适配，不另写业务标准。

## 决策与边界

1. 普通 `xc ask` **自动串联**判断与生成，用户无需按推文 ID 手工调用 `decide`。
2. 不是以“自动过滤 80%”作为 KPI。过滤只取决于每条的相关性与营销判定，保留所有符合条件的证据；模型原始概率连同过滤结果写入判决记录。
3. 生成模型收到带唯一 `S1`、`S2` 标签的来源。引用缺失或超出范围视为错误，不能静默造出报告。来源只来自书签，或明确的 `demo_seed` / `client_supplied` 输入。
4. 只有显式调用 `ask` 或 `research` 才消耗 AI 额度；页面刷新、X 同步及 Discovery 定时任务不调用研究流水线。
5. 搜索选择 **FTS5 + 词法容错** 作为当前可复现召回机制。没有 Vectorize 绑定时，不冒称已实现向量检索；后续真正接向量索引时，应保留 FTS 召回与来源核验。
6. 远端 D1 索引只是书签表的可重建投影；触发器在书签插入、更改及删除时同步。Discovery 24 小时物理删除和双阶段 Bookmark Promotion 不作任何改变。
7. 已安装 `xcollect` / 包装好的 `xc`，不自动重复安装。所有新功能由原有分发器传给新增子命令。
8. 对有隐私属性的已收藏内容，`--provider direct` 会将模型输入发送到 Cloudflare（选 DeepSeek 时再发送通过筛选的证据给 DeepSeek）。必须在文档中透明说明，不可把本地模式解释成“所有数据不出本机”。

## 本轮验收与未验收

已覆盖：自然语言提取、SQLite FTS5 排序补充、D1 FTS5 增删改触发器、自动逐条模型判决、模型筛除后的生成式综合、来源交叉检查、双模型接口适配、CLI 文件导出、无证据时不生成。

未覆盖：Cloudflare 真实账户中模型调用成功与延迟、Cloudflare Access 生产鉴权策略、D1 迁移的远端执行、Vectorize 语义索引、全部 X 历史证据的准确性。以上不能用离线测试通过来冒充。

## Goodhart 防护

- 目标：用户得到可追溯的研究结论，而非命令数、测试数、淘汰率。
- 验收：一条自然语言命令必须穿过全部四层；若没有数据、密钥、模型或有效引用，明确失败/无证据，不返回假研究报告。
- 学习：离线模型概率不直接重写已有的用户兴趣权重；沿用现有自校准反馈架构。
