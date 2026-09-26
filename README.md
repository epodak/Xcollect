# 𝕏 书签智能聚合看板 (Xcollect)

<p align="center">
  <img src="https://img.shields.io/badge/Cloudflare_Workers-Python-F38020?style=for-the-badge&logo=cloudflare&logoColor=white" alt="Cloudflare Workers">
  <img src="https://img.shields.io/badge/Database-Cloudflare_D1-0051C3?style=for-the-badge&logo=sqlite&logoColor=white" alt="Cloudflare D1">
  <img src="https://img.shields.io/badge/Package_Manager-pnpm-4A4A4A?style=for-the-badge&logo=pnpm&logoColor=white" alt="pnpm">
  <img src="https://img.shields.io/badge/Design-Petrol_Teal-005b5b?style=for-the-badge" alt="Petrol Teal UI">
  <img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License">
</p>

> 基于 **Cloudflare Python Workers**、**Cloudflare D1** 边缘数据库与现代前端（深青 Petrol Teal 视觉系统）构建的 Twitter / 𝕏 书签实时双向同步中枢与知识资产库。

---

## ✨ 核心特性

- 🔄 **𝕏 官方书签双向云同步**：通过 Web 凭据直接对接 𝕏 官方 GraphQL API，在看板中实时同步、收藏或一键解除云端书签，告别昂贵的官方企业级 API。
- 🎨 **Petrol Teal 极客视觉美学**：精心调优的深青暗黑/明亮双主题，卡片悬浮微动效、图片/多视频画廊预览、响应式瀑布流布局。
- 🏷️ **推文智能领域打标**：内置自动分类与二级细分引擎（人工智能与 Agent、技术架构与开发、开源精选与工具、产品设计与思考、前沿资讯与研读），支持 Workers AI 动态自适应扩展与 `config.toml` 用户自定义配置。
- 🚀 **双模运行底座 (Dual Architecture)**：
  - **本地独立模式 (Pure Python)**：只需 `python local_server.py`，0 安装依赖，自带轻量 JSON 存储与 API 模拟服务。
  - **边缘生产模式 (Cloudflare Workers)**：利用 `compatibility_flags = ["python_workers"]` 在全球边缘节点无服务执行 Python 逻辑并持久化于 D1 数据库。
- 🛡️ **严格 12-Factor 工程卫生契约**：
  - 凭据完全物理隔离：私有密钥只存本地 `.env`（绝不上库），提供 100% 1:1 脱敏的 `.env.example`。
  - 工程解耦配置：非敏感参数（端口、超时、开关）统一收敛至 `config.toml`。
  - 一行冒烟自检：内置 `python local_server.py --check` 快速自验入口。

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

### 3. 方式 B：Cloudflare Workers + D1 边缘无服务部署

利用 Cloudflare Workers 免费层全球边缘加速与 D1 关系型数据库：

#### ① 安装依赖
```bash
pnpm install
```

#### ② 创建并绑定 Cloudflare D1 数据库
```bash
# 1. 创建 D1 数据库
npx wrangler d1 create x-bookmarks

# 2. 将控制台输出中的 database_id 填入 wrangler.jsonc 中：
# "database_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# 3. 初始化数据库表结构 (本地或远端)
pnpm run d1:init:local
pnpm run d1:init:remote

# 4. (可选) 导入预设推文种子数据 (包含 400+ 精选技术推文)
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

项目通过模拟官方 Web 端请求实现书签双向同步，仅需两个只读 Cookie 字段：

1. 在浏览器中打开并登录 [x.com](https://x.com)。
2. 按 `F12` 打开开发者工具，切换到 **Application (应用程序)** -> **Cookies** -> `https://x.com`。
3. 搜索并复制以下两个字段的值：
   - `auth_token`：你的身份验证令牌。
   - `ct0`：你的 CSRF 安全令牌。
4. 将它们粘贴保存至本地 `.env` 文件即可。

> ⚠️ **安全说明**：这两个凭据仅用于本地服务或你私人部署的 Cloudflare Worker 代理向推特发送官方书签查询，`.env` 已被 `.gitignore` 严格忽略，绝对不会提交到公开版本库。

---

## 📁 目录结构

```text
Xcollect/
├── .env.example          # 敏感凭据脱敏契约模板 (1:1 影子镜像)
├── config.toml           # 集中解耦配置文件 (端口、运行参数等)
├── wrangler.jsonc        # Cloudflare Python Workers 配置文件
├── package.json          # pnpm 包管理器与脚本入口
├── local_server.py       # 本地独立全功能 Python 服务 (支持 --check 自验)
├── src/
│   └── entry.py          # Cloudflare Python Worker 边缘业务网关与 D1 交互入口
├── public/               # 前端静态看板资产 (Petrol Teal 视觉系统)
│   ├── index.html        # 主看板 SPA 页面
│   ├── css/              # 模块化样式 (cards, layout, modal, theme)
│   └── js/               # 模块化逻辑 (api, app, render)
└── scripts/
    ├── schema.sql        # Cloudflare D1 数据库 DDL 表结构
    ├── seed_data.json    # 精选预置技术推文种子数据
    └── seed_d1.py        # D1 种子数据一键迁移与 SQL 生成工具
```

---

## 🤝 参与贡献与开发契约

本项目严格遵循 [Agent Relay Hygiene (工程卫生契约)](./AGENTS.md)：
1. **单一包管理器**：严格使用 `pnpm`，禁止使用 `npm` 或 `yarn`。
2. **12-Factor 双轨分工**：敏感机密严格收敛在 `.env`，非敏感参数统一由 `config.toml` 解耦。
3. **闭环自验**：每次提交修改必须保证 `python local_server.py --check` 通过。

---

## 📄 License

本项目采用 [MIT License](./LICENSE) 开源协议。
