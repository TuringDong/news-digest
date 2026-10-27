# 云端日报调度器

Cloudflare 负责定时唤醒；GitHub Actions 继续执行仓库原有的抓取、双语写稿、排版、SMTP 和归档逻辑。电脑、VPN、ChatGPT 应用均不参与定时运行。

## 正式计划（北京时间）

- 07:45：触发 GitHub 生成日报，准备完成后等待 08:00 发送。
- 07:50、07:55：检查已触发的任务，正在运行或已成功时不重复启动，失败时补跑。
- 08:00、08:05：异常补偿。延迟补偿不会假装按时完成。
- GitHub 原生 schedule 保留为备用。有效的当天发送凭据避免重复日报。

电子邮件最终入箱时间仍受调度平台、运行器、新闻/API 响应和邮件服务影响，不能保证每一天精确到秒；正常路径提前准备、8 点提交 SMTP。

## GitHub 授权

使用属于仓库所有者的私有 GitHub App，仅安装到 `TuringDong/news-digest`：Actions 读写、Contents 只读。安装令牌每次按需申请且限定到这个仓库，不使用整账号的个人登录令牌。专用 App 私钥用 AES-GCM 加密后保存在 D1，密钥通过 Worker Secret 提供。安装入口与后台管理密钥分离。

管理员通过受限安装入口创建并安装 App；安装完成后才能实际启动工作流。`/health` 只显示是否已连接，不公开凭据或私人运行配置。

## 部署与测试

1. `wrangler d1 execute news-digest-scheduler --remote --file schema.sql`
2. 安全设置随机 256-bit `ADMIN_KEY` Worker Secret；保留安全备份，不能随意轮换，否则旧加密数据将无法解密。
3. `wrangler deploy`
4. 完成 GitHub App 创建和单仓库安装。
5. 通过后台接口安排一次带明确标识的验收邮件。由真实 Cloudflare cron 触发 GitHub，核对云端触发记录、GitHub 运行记录、实际提交 SMTP 时间和收件结果。
6. 验收后删除配置中的临时 `* * * * *` cron，保留正式的两条 cron。

测试：`node --test worker.test.mjs`。仓库 Python 测试：`python -m unittest discover -s tests -v`。

2026-10-27 已完成真实云端定时验收：Cloudflare 于北京时间 14:10 触发 GitHub Actions，任务等待至 14:13 发送验收邮件，收件人确认收到。对应运行编号为 `40459531643`。临时一分钟 cron 已从正式配置移除，只保留每日正式计划。首次正式早间运行仍需以次日实际记录和收件为准。

随后应用户要求，完成当天关机验收：不早于北京时间 14:55 自动触发，目标 15:00 发送一次测试邮件，用户确认收到并报告成功。验收后已移除临时一分钟 cron，只保留正式早间计划。探针具有一次发送标识和 15 分钟有效期，不会在次日重复发送。后台 `/admin/probe` 可选 `not_before` ISO 时间，限定未来 15 分钟内。
