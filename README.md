# 每日 AI 新闻日报（云端版）

每天 **08:07 左右（北京时间）** 自动生成中英双语新闻日报并发到邮箱。
**跑在 GitHub 的服务器上，你的电脑关机、断电、断网都不影响。**

> 为什么不是 8:00 整：GitHub 的 cron 在整点 UTC 最拥堵，单条整点任务被丢弃是常事。
> 所以配了 **08:07 / 08:27 / 08:47 / 09:17 四个触发点**，哪次被调度到就哪次发；
> 后面几次看到 `outbox/<日期>.sent` 标记会直接跳过，**你只会收到一封**。

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
| `SMTP_USER` | 发件邮箱，如 `you@qq.com` |
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

**1. GitHub 的 cron 不可靠——这是本项目最坑的一点。**
不只是「不准点」，而是**可能整次都不触发**：Actions 页面里连一条运行记录都没有。实测踩过一次
（配了单条 `0 0 * * *`，次日 08:00 完全没跑）。
对策就是现在这套：**四个非整点触发时间 + 幂等标记**。只要有一次被调度到就成，
重复的触发会被 `.sent` 标记挡掉。要严格准点只能换国内云函数或外置 cron 服务。

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

## 失败告警

工作流最后有一个 `if: failure()` 的步骤：**任何一步失败，就用同一个 QQ 邮箱给你发一封告警信**，
标题是「⚠️ 今日 AI 日报没发出去 · 日期」，正文会写清卡在哪一步、具体原因、怎么处理。

告警靠 `status.json`（记录进度）和 `raw.json`（判断抓取是否成功）来定位问题，覆盖四类情况：

| 卡在哪 | 告警会说 |
| --- | --- |
| 启动就崩 | 没有进度记录，去看日志第一条报错 |
| 抓取阶段 | 哪个源出错了 / 完全没抓到 |
| 写稿阶段 | API key 无效、余额不足（402）等 |
| 发送阶段 | 授权码填错、SMTP 服务被关 |

**一个覆盖不到的死角**：如果故障本身是 SMTP 授权码失效，告警邮件也发不出去。
那种情况只能靠 GitHub 自己的失败通知，所以两边都开着最稳妥。

本地验证告警文案（不发信）：

```powershell
python notify_failure.py --dry-run
python notify_failure.py --test      # 真发一封，标题带［测试］前缀
```

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `run.py` | 主流程，串起下面四步，并记录进度喂给告警 |
| `fetch_news.py` | 抓 13 个 RSS 源，按时间窗口过滤、去重、容错 |
| `write_digest.py` | 调 DeepSeek 写双语稿，并校验链接不许自造 |
| `render.py` | 渲染成 HTML + 纯文本 |
| `mailer.py` | 发信（465 SSL / 587 STARTTLS 都支持） |
| `notify_failure.py` | 失败时发告警信 |
| `check_api.py` | 单独验证 API key 与余额 |
| `show_raw.py` | 打印抓取概况，排查某个源是否挂了 |
| `outbox/` | 每天成品归档（会被自动提交进仓库） |

## 改内容风格

编辑 `write_digest.py` 里的 `SYSTEM_PROMPT` 和 `build_user_prompt()` 的「硬性规则」部分。
比如想调整科技与其他领域的比例、想加固定分区、想改语气，都在那里改。
