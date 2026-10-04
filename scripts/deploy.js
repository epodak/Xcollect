// 一键正式部署脚本 —— pnpm pub (cf-astro-deploy SOP)
import { execSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import os from 'node:os';
import net from 'node:net';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

// 0. 分支安全校验：正式部署只允许在 main 分支执行
try {
  const currentBranch = execSync('git rev-parse --abbrev-ref HEAD', { encoding: 'utf-8', cwd: root }).trim();
  if (currentBranch !== 'main') {
    console.error(`\n❌ [DEPLOY REFUSED] 拒绝部署：当前处于分支 '${currentBranch}'！`);
    console.error(`⚠️ 线上正式部署严格限定只能在 'main' 分支上执行。\n`);
    process.exit(1);
  }
} catch (e) {
  console.warn('⚠️ 提示：未检测到 Git 分支，继续部署流程。');
}

// 1. 执行门禁冒烟与预部署配置对齐
console.log('🔍 执行本地门禁自检与配置投影...');
execSync('pnpm run check', { stdio: 'inherit', cwd: root });
execSync('python scripts/sync_config.py', { stdio: 'inherit', cwd: root });
execSync('python scripts/check_cloud_schedule.py', { stdio: 'inherit', cwd: root });

// 2. 智能获取 Cloudflare Token (支持 ~/token.bashrc)
let token = process.env.CLOUDFLARE_FORAI_API_TOKEN;
if (!token) {
  try {
    const tb = path.join(os.homedir(), 'token.bashrc');
    if (fs.existsSync(tb)) {
      const match = fs.readFileSync(tb, 'utf-8').match(/CLOUDFLARE_FORAI_API_TOKEN=["']?([^"'\r\n]+)["']?/);
      if (match) token = match[1];
    }
  } catch (e) {}
}
if (!token) token = process.env.CLOUDFLARE_API_TOKEN;
if (!token) {
  console.error('❌ 未找到 Cloudflare API Token 凭证！');
  process.exit(1);
}

// 3. 本地网络代理智能探活 (支持本地 sing-box: 2080)
async function detectProxy() {
  if (process.env.HTTPS_PROXY || process.env.HTTP_PROXY || process.env.ALL_PROXY) {
    return null;
  }
  return new Promise((resolve) => {
    const socket = new net.Socket();
    socket.setTimeout(300);
    socket.on('connect', () => {
      socket.destroy();
      resolve('http://127.0.0.1:2080');
    });
    socket.on('timeout', () => {
      socket.destroy();
      resolve(null);
    });
    socket.on('error', () => {
      resolve(null);
    });
    socket.connect(2080, '127.0.0.1');
  });
}

const detectedProxy = await detectProxy();
const env = { ...process.env, CLOUDFLARE_API_TOKEN: token };
delete env.CLOUDFLARE_FORAI_API_TOKEN;

if (detectedProxy) {
  console.log(`🌐 智能检测到本地代理环境 (${detectedProxy})，已自动注入。`);
  env.HTTPS_PROXY = detectedProxy;
  env.HTTP_PROXY = detectedProxy;
}

try {
  console.log('🚀 正在部署至 Cloudflare Workers...');
  execSync('pnpm exec wrangler deploy', { stdio: 'inherit', cwd: root, env });
  console.log('\n🎉 部署成功！\n');
} catch (e) {
  console.error('\n❌ 部署失败，请检查 Cloudflare 认证凭证与网络。');
  process.exit(1);
}
