<p align="center">
  <img src="./public/images/logo.jpg" alt="Xcollect Logo" width="160px" style="border-radius: 28px; box-shadow: 0 10px 30px rgba(13, 148, 136, 0.4);">
</p>

<h1 align="center">Xcollect — Exploration Collector</h1>
<p align="center"><b>从 Twitter / 𝕏 收藏开始，构建跨互联网的个人 Exploration Memory Layer</b></p>

<p align="center">
  <img src="https://img.shields.io/badge/Cost-100%25_Free_Tier-brightgreen?style=for-the-badge&logo=cloudflare" alt="100% Free">
  <img src="https://img.shields.io/badge/Cloudflare_Workers-Python-F38020?style=for-the-badge&logo=cloudflare&logoColor=white" alt="Cloudflare Workers">
  <img src="https://img.shields.io/badge/Database-Cloudflare_D1-0051C3?style=for-the-badge&logo=sqlite&logoColor=white" alt="Cloudflare D1">
  <img src="https://img.shields.io/badge/Package_Manager-pnpm-4A4A4A?style=for-the-badge&logo=pnpm&logoColor=white" alt="pnpm">
  <img src="https://img.shields.io/badge/Design-Petrol_Teal-005b5b?style=for-the-badge" alt="Petrol Teal UI">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
</p>

> **X in Xcollect means Exploration, not X / Twitter.**
>
> 当前版本从 Twitter / 𝕏 书签切入：基于 **Cloudflare Python Workers**、**Cloudflare D1** 与 Local-First 架构，把收藏从“信息坟场”变成可重新检索、理解和组织的个人知识资产。
>
> Twitter / 𝕏 是 **Adapter 01**，不是 Xcollect 的产品边界。

<p align="center">
  <img src="./public/images/feat_overview.png" alt="Xcollect 看板全景预览" width="100%" style="border-radius: 12px; box-shadow: 0 12px 32px rgba(0, 0, 0, 0.35);">
</p>

---

## 🧭 为什么叫 Xcollect？

互联网上有很多不同的“收藏”动作：

```text
Twitter Bookmark
GitHub Star
Browser Bookmark
Reddit Save
YouTube Watch Later
RSS Star
Maps Saved Place
Wishlist
        │
        ▼
   Exploration.Save
```

它们表面上属于不同平台，实际表达的是同一种弱未来意图：

> **“这个东西现在看起来有价值，我以后可能会回来。”**

问题是，大多数平台只保存了 **item + timestamp**，却丢掉了更重要的信息：

- 我当时为什么收藏它？
- 当时正在探索什么问题？
- 它和哪个项目有关？
- 有没有出现更好的替代品？
- 现在还值得重新看吗？

Xcollect 的长期目标不是帮助你“收藏更多”，而是：

> **让曾经觉得有价值的东西，未来还能被找到、理解、关联并重新行动。**

因此核心路径是：

```text
Encounter
   ↓
Collect
   ↓
Normalize
   ↓
Enrich
   ↓
Organize
   ↓
Resurface
   ↓
Act
```

完整设计见 [Xcollect Roadmap](./docs/ROADMAP.md)。

---

## 🗺️ Roadmap

Xcollect 正在从一个 Twitter / 𝕏 书签工具演化为 adapter-driven 的 Exploration 平台：

```text
                         Xcollect Core
                              ▲
                              │
                    Acquisition Adapters
          ┌───────────────────┼───────────────────┐
          │                   │                   │
       Twitter/X           GitHub              Browser
       Adapter 01          Stars               Extension
          │                   │                   │
       Reddit             YouTube               RSS
          └───────────────────┼───────────────────┘
                              │
                         Normalization
                              │
                           Enrichment
                              │
                     Knowledge Topology
                              │
                         Resurfacing
```

当前阶段：

- ✅ **Phase 0 — Twitter / 𝕏 vertical slice**：书签同步、本地优先存储、AI 分类、二级标签、知识拓扑重整。
- ⏭️ **Phase 1 — Source-neutral Core**：把 Twitter-specific 数据模型收敛成统一 `ExplorationItem`。
- ⭐ **Phase 2 — GitHub Stars Adapter**：回答“我当时为什么 Star 它？现在还值得用吗？”
- 🌐 **Phase 3 — Browser Capture**：Chrome / Chromium Extension、Userscript、右键 Save to Xcollect。
- 📚 **Phase 4 — Reddit / YouTube / RSS / HN / Podcasts / Email**。
- 🗺️ **Phase 5 — Places / Wishlist / Travel 等非传统知识型 Exploration**。
- 🔁 **Long-term — Resurfacing Engine**：不仅收藏，还主动发现旧收藏与当前项目、当前探索主题之间的新关联。

详见：[docs/ROADMAP.md](./docs/ROADMAP.md)

---

## ✨ 当前核心特性：Twitter / 𝕏 Adapter 01

- 🔄 **𝕏 官方书签双向云同步**：通过 Web 凭据直接对接 𝕏 官方 GraphQL API，在看板中实时同步、收藏或一键解除云端书签，告别昂贵的官方企业级 API。
- 🏡 **本地优先哲学 (Local-First)**：**绝不强求用户搭建个人网站**。无需买域名、无需配置云端，运行 `python local_server.py` 即可在本地硬盘安全存放推文数据，在 localhost 极速浏览。
- 📦 **多级存储平滑降级 (Storage Cascade)**：
  - 🥇 **Cloudflare D1 关系型数据库**（默认推荐，支持海量推文极速索引）
  - 🥈 **Cloudflare KV 键值存储**（100% 免费开箱即用，每日 10 万次读取免建表）
  - 🥉 **本地单文件存储**（`seed_data.json`，零任何第三方依赖，单机离线可用）
- 🧠 **可插拔多级 AI 算力体系 (Pluggable AI Matrix)**：
  - 🥇 **用户自定义大模型**：无缝对接 DeepSeek、OpenAI、本地 Ollama 等任何 OpenAI 兼容 API。
  - 🥈 **Cloudflare Workers AI**：零配置免费赠送额度（采用 Meta Llama 3.1-8b-instruct-fast / 3.2 矩阵）。
  - 🥉 **本地关键词规则引擎**：纯正则与高精语义打标，零网络依赖、零延迟、断网亦可 100% 兜底。
- 🧬 **低扰动知识拓扑重整化 (Topology Renormalization)**：
  - **日常收藏保持惯性**：新推文严格吸附在现有大类中，提取自由二级标签（`sub_category`），标记为 `projected`，保证看板一级专区不随单条收藏频繁晃动；
  - **相变周期全局重整**：未固化条目累积达到阈值（如 30 条）或分类密度失衡时，由宏观聚类算法执行分裂/合并，批量固化为 `settled` 状态。
- 🎨 **Petrol Teal 极客视觉美学**：精心调优的深青暗黑/明亮双主题，卡片悬浮微动效、图片/多视频画廊预览、响应式瀑布流布局。
- 🛡️ **严格 12-Factor 工程卫生契约**：敏感机密严格存入 `.env`（提供 1:1 脱敏镜像 `.env.example`），解耦参数统一置于 `config.toml`，内置一行冒烟自检 `python local_server.py --check`。

---

## 🚀 极速上手

### 1. 克隆项目与配置凭据

```bash
git clone https://github.com/epodak/Xcollect.git
cd Xcollect
```

复制敏感凭据契约模板：
```bash
cp .env.example .env
```
在 `.env` 中填入你的 𝕏 平台 Web 凭据（如何获取见下文 [凭据获取指南](#-x-平台凭据获取指南)）：
```env
X_AUTH_TOKEN=你的x_auth_token
X_CT0=你的x_ct0_csrf_token
```

---

### 2. 方式 A：本地纯 Python 极速运行（推荐初次体验）

无需 Node.js，无需安装庞大的外部依赖，标准 Python 3.10+ 环境即可直接启动：

```bash
# 执行工程卫生环境冒烟自检
python local_server.py --check

# 启动本地服务 (默认监听 8089 端口)
python local_server.py
```
打开浏览器访问：`http://localhost:8089` 即可畅享完整看板与实时云端同步功能！

---

### 3. 方式 B：Cloudflare Workers + D1 边缘无服务部署 (100% 永久免费)

本项目经过严格的资源优化设计，**完全运行在 Cloudflare 官方免费额度之内，0 运维成本，无需绑定信用卡**：

> [!TIP]
> **💰 Cloudflare 免费配额深度说明（个人使用充裕度 > 1000 倍）：**
> - ⚡ **Cloudflare Workers**：每日 **100,000 次免费请求**（个人看板日常访问仅需数十次）。
> - 🗄️ **Cloudflare D1 数据库**：每日 **5,000,000 次读操作 + 100,000 次写操作**，免费存储高达 **500 MB**（存储上万条推文仅占用数十 MB）。
> - 🤖 **Cloudflare Workers AI**：每日赠送 **10,000 神经元计算额度**（支持每日自动分类数百篇最新推文）。
> - 🌐 **全球 CDN 静态资产**：自带全球 Anycast 边缘加速，无限带宽托管。
> - 💸 **零 API 费用**：直接基于个人 Web 凭据同步书签，彻底告别推特每月 $100+ 的官方昂贵 API。

#### ① 安装依赖
```bash
pnpm install
```

#### ② 配置 Cloudflare 与绑定 D1 数据库
```bash
# 1. 复制配置文件模板为本地私有配置 (wrangler.jsonc 已被 .gitignore 隔离，绝不上库)
cp wrangler.example.jsonc wrangler.jsonc

# 2. 创建 D1 数据库 (Cloudflare 账号内秒级免费生成，无需信用卡)
npx wrangler d1 create x-bookmarks

# 3. 将控制台输出中的 database_id 填入本地的 wrangler.jsonc 中
# "database_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# 4. 初始化数据库表结构 (本地或远端)
pnpm run d1:init:local
pnpm run d1:init:remote

# 5. (可选) 导入预设推文种子数据
pnpm run d1:seed:local
pnpm run d1:seed:remote
```

#### ③ 本地边缘模拟与正式发布
```bash
# 本地模拟 Cloudflare Worker 运行
pnpm run dev

# 一键部署至 Cloudflare 生产环境
pnpm run deploy
```

---

## 🔑 𝕏 平台凭据获取指南

项目通过模拟官方 Web 端请求实现书签双向同步，仅需两个 Cookie 字段：

1. 在浏览器中打开并登录 [x.com](https://x.com)。
2. 按 `F12` 打开开发者工具，切换到 **Application (应用程序)** -> **Cookies** -> `https://x.com`。
3. 搜索并复制以下两个字段的值：
   - `auth_token`：你的身份验证令牌。
   - `ct0`：你的 CSRF 安全令牌。
4. 将它们粘贴保存至本地 `.env` 文件即可。

> ⚠️ **安全说明**：这两个凭据仅用于本地服务或你私人部署的 Cloudflare Worker 代理向推特发送书签查询，`.env` 已被 `.gitignore` 严格忽略，不应提交到公开版本库。

---

## 📁 目录结构

```text
Xcollect/
├── .env.example          # 敏感凭据脱敏契约模板
├── config.toml           # 集中解耦配置文件
├── wrangler.jsonc        # Cloudflare Python Workers 配置文件
├── package.json          # pnpm 包管理器与脚本入口
├── local_server.py       # 本地独立全功能 Python 服务
├── docs/
│   └── ROADMAP.md        # Exploration 平台长期路径图
├── src/
│   └── entry.py          # Cloudflare Python Worker 边缘业务网关与 D1 交互入口
├── public/               # 前端静态看板资产
│   ├── index.html
│   ├── css/
│   └── js/
└── scripts/
    ├── schema.sql
    ├── seed_data.json
    └── seed_d1.py
```

---

## 🤝 参与贡献与开发契约

本项目严格遵循 [Agent Relay Hygiene (工程卫生契约)](./AGENTS.md)：

1. **单一包管理器**：严格使用 `pnpm`，禁止使用 `npm` 或 `yarn`。
2. **12-Factor 双轨分工**：敏感机密严格收敛在 `.env`，非敏感参数统一由 `config.toml` 解耦。
3. **闭环自验**：每次提交修改必须保证 `python local_server.py --check` 通过。
4. **Source-neutral direction**：新增能力优先考虑是否属于 Xcollect Core，还是某个 source adapter，避免把核心继续耦合到 Twitter / 𝕏。

---

## 📄 License

本项目采用 [MIT License](./LICENSE) 开源协议。
