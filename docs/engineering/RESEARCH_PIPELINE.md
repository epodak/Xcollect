# 自然语言研究管线 — Xcollect CLI / Cloudflare Worker

## 已交付的命令

在你现有的 Windows / Git Bash 全局 `xc` 包装器中：

```bash
xc ask "我想了解 Opus 5.5"
xc ask "最近的 Grok Bot 相关技术讨论" --limit 20 --max-candidates 5
xc research "Jev" --out ./notes/jev
xc research "Opus 5.5" --out ./notes/opus --json
```

四层会自动串联。前置条件是有可用的研究 AI 提供商凭据，当前并非无密钥即可联网调用。

### 方法 A：直连 Cloudflare AI，不依赖部署本项目 Worker

在你本机的安全环境变量中提供拥有 Workers AI Run 权限的 API Token：

```bash
export CLOUDFLARE_API_TOKEN="<private token>"
# 如 wrangler.jsonc 已配置同一账户，可不再提供 CLOUDFLARE_ACCOUNT_ID
xc ask "Opus 5.5" --provider direct
xc research "Jev" --out notes/jev --provider direct
# 用 Cloudflare Clef 做判断、DeepSeek 做最终综合（须已有 CUSTOM_AI_API_KEY）
xc research "Jev" --provider direct --generator deepseek --out notes/jev-deepseek
```

注意：Token 不写进代码、Git、公共 `.cmd` / Bash 包装器。API 会把候选推文发给 Cloudflare；如果使用 DeepSeek，也会把筛选后的来源发送给 DeepSeek。

Jev 属于按量付费的第三方模型，必须明确指定：

```bash
xc ask "Jev" --provider direct --model jev --allow-jev
```

### 方法 B：托管在已有 Worker、读取远端 D1

Worker 配置专属 `XCOLLECT_API_TOKEN` Secret，CLI 进程设置：

```bash
export XCOLLECT_API_BASE="https://x.daduiot.com"
export XCOLLECT_API_TOKEN="<private API token>"
xc --source cloud ask "我想了解 Opus 5.5" --provider worker
xc --source cloud research "Jev" --provider worker --out notes/jev
```

`POST /api/v1/research` 使用请求体 `{query, model, limit, max_candidates}`，由 Worker 完成 D1 检索、模型过滤、综合与引用映射。

`--source local` 可以把本地召回的书签作为 `sources` 输入发送给受认证的 Worker，Worker 不把传入材料写进 D1。

**上线警戒：** 只保护新 `/api/v1/*` 不够。现存 `/api/tweets`、`/api/feed` 和其他历史路由也必须处于 Cloudflare Access 等整体保护之下。不要在生产路由未加固时对外部署私有内容。

## FTS5 索引初始化

Local Profile：查询时在 Python 内存中从本地 JSON 构建 FTS5，不写库；不依赖配置。

Cloud D1：原有数据库先按已存在的 `scripts/schema.sql` 初始化，再执行一次：

```bash
pnpm run d1:fts:local
# 审核远端数据库备份与权限后，才执行：
pnpm run d1:fts:remote
```

迁移文件：`scripts/migrations/0002_bookmarks_fts5.sql`。它为 **tweets** 建立外部内容 FTS5 和增删改触发器，并重建历史书签索引。迁移未执行时，研究查询会退回旧词法召回，报告包含 `retrieval_backend` 标记。FTS5 不等于向量相似性：尚未配置 Vectorize 资源与同步删除机制，不能声称已完成向量召回。

## 实际成果与溯源

研究命令写出：

| 文件 | 内容 |
|---|---|
| `report.md` | LLM 研究综述；来源编号与原推链接由程序附上 |
| `sources.jsonl` | 通过判断的典范原文记录；不覆盖 `body_raw` |
| `posts/*.md` | 每条推文原文 Markdown |
| `decisions.jsonl` | 每个候选的概率回答、判决与拒绝原因 |
| `research.json` | 使用的数据配置、生成模型与数量 |
| `manifest.json` | 证据包元数据，来源范围与生成标记 |

如果既没有通过判断的证据，也没有合法来源编号，则不伪造“研究结果”；不以固定 80% 淘汰率硬压候选数量。

本地 `data/xcollect.json` 缺失时，现有 CLI 会回退使用仓库自带的 547 条演示种子，研究报告将标注 `demo_seed`，不能将其当作真实收藏。要研究自己的收藏，需要先同步真实书签。

## 验收命令

```bash
python scripts/check_research.py
pnpm run check
xc ask --help
```

离线测试使用替代 AI 对象，不产生真实 Token 费用。真实模型调用必须另做账号、费用、网络安全和响应质量验收。
