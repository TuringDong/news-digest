# 每日 AI 新闻日报（云端版）

每天早上 **08:00（北京时间）** 自动生成中英双语新闻日报并发到邮箱。
**跑在 GitHub 的服务器上，你的电脑关机、断电、断网都不影响。**

---

## 它和本地版的区别

| | 本地版（`news-digest/`） | 云端版（本目录） |
| --- | --- | --- |
| 电脑关机时 | 不发 | **照发** |
| 谁来写稿 | DSH 里的模型（我） | DeepSeek API |
| 新闻从哪来 | 联网搜索工具 | 13 个 RSS 源（无需 key） |
| 依赖 | Python + DSH 运行 | 无第三方依赖 |
| 成本 | 0 | DeepSeek API 调用费（每天几分钱）+ Actions 免费额度 |

两个版本可以并存，也可以只用这一个。排版样式完全相同。

---

## 部署步骤

### 1. 拿到 DeepSeek API key

去 <https://platform.deepseek.com> 注册 → API keys → 创建一个，形如 `sk-xxxxxxxx`。
**记得充值几块钱**，余额为 0 时接口会直接失败（错误 402）。

### 2. 建一个 GitHub 仓库

建议**私有仓库（Private）**——邮件内容会以归档形式提交进仓库。

### 3. 把本目录推上去

```bash
cd cloud/news-digest
git init
git add .
git commit -m "init: daily digest bot"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

> ⚠️ 上传前确认没有 `.env` 文件躺在目录里（`.gitignore` 已挡，但自己再确认一眼）。

### 4. 配 4 个 Secrets

仓库页面 → **Settings → Secrets and variables → Actions → New repository secret**：

| Name | 值 |
| --- | --- |
| `DEEPSEEK_API_KEY` | `sk-xxxxxxxx` |
| `SMTP_USER` | 发件邮箱，如 `2960792563@qq.com` |
| `SMTP_PASS` | QQ 邮箱的 **16 位 SMTP 授权码**（不是登录密码） |
| `MAIL_TO` | 收件邮箱；多个用英文逗号分隔 |

### 5. 先手动跑一次（重要）

仓库页面 → **Actions** → 左侧 `Daily AI & Tech Digest` → **Run workflow**：

- 第一次建议把 **只生成不发信** 勾上 → 验证抓取和写作都能跑通，但不会真的发邮件
- 跑通后，再取消勾选跑一次 → 这会真的发一封，用来确认 SMTP 通不通

点开运行记录能看到每一步的日志，包括每个 RSS 源抓到几条、哪些源失败。

### 6. 收工

之后每天北京时间 08:00 自动执行，无需任何操作。

---

## 需要知道的坑

**1. GitHub 的 cron 不保证准点。**
整点是最挤的时候，实际触发常延迟 3–15 分钟。8:05 收到属正常。要严格准点，得换国内云函数。

**2. QQ 邮箱可能对境外 IP 发信有风控。**
GitHub 的服务器在境外。第 5 步「真发一封」就是用来验证这件事的。如果报认证失败或被退信，两条路：
- 换 587 端口（把 `SMTP_PORT` 改成 `587`，走 STARTTLS）
- 改用国内云函数部署（同一套代码，几乎不用改）

**3. 仓库连续 60 天无提交会被 GitHub 停用定时任务。**
本工作流每次运行都会把当天日报提交进 `outbox/`，等于自带保活，不用管。

**4. 定时任务只在默认分支（main）上生效。**
别把工作流文件放在别的分支里等它跑。

**5. 免费额度。**
私有仓库每月 2000 分钟 Actions 额度，这个任务每天 1–2 分钟，够用 3 年。

---

## 本地调试

```powershell
# 0) 先确认 key 能用、账户有钱（30 秒，强烈建议先跑这个）
$env:DEEPSEEK_API_KEY="sk-xxxx"
python check_api.py

# 只抓新闻，看看源通不通（不需要任何 key）
python fetch_news.py --out raw.json

# 看看会发给模型什么内容（不需要 key）
python write_digest.py --raw raw.json --show-prompt

# 用现成稿件测试排版，不发信
python run.py --digest digest.json --dry-run

# 完整跑一遍（需要 key 和 SMTP 环境变量）
$env:DEEPSEEK_API_KEY="sk-xxx"; $env:SMTP_USER="..."; $env:SMTP_PASS="..."; $env:MAIL_TO="..."
python run.py
```

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `run.py` | 主流程，串起下面四步 |
| `fetch_news.py` | 抓 13 个 RSS 源，按时间窗口过滤、去重、容错 |
| `write_digest.py` | 调 DeepSeek 写双语稿，并校验链接不许自造 |
| `render.py` | 渲染成 HTML + 纯文本 |
| `mailer.py` | 发信（465 SSL / 587 STARTTLS 都支持） |
| `outbox/` | 每天成品归档（会被自动提交进仓库） |

## 改内容风格

编辑 `write_digest.py` 里的 `SYSTEM_PROMPT` 和 `build_user_prompt()` 的「硬性规则」部分。
比如想调整科技与其他领域的比例、想加固定分区、想改语气，都在那里改。
