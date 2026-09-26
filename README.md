# Arena 五类榜单监控 V1

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md)

这是一个轻量级监控工具：每天检查 5 个 Arena 一级榜单，只在命中 4 类高价值变化时生成简报。

## 首版范围

| 业务类别 | 官方数据 subset | 监控分类 |
|---|---|---|
| Text | `text_style_control` | Overall |
| Agent | `agent` | Overall |
| WebDev | `webdev` | Overall |
| Text-to-Image | `text_to_image` | Overall |
| Image Edit | `image_edit` | Overall |

V1 只通知：

1. 新模型进入榜单
2. 模型从榜单消失
3. 榜首变化
4. 进入或跌出 Top 3 / Top 10

普通名次波动、分数变化、置信区间变化和票数增长暂不通知。模型从榜单消失时只写“消失”；除非 Arena 官方明确说明，否则不自动判断为“弃用”。

## 本地运行

项目只使用 Python 标准库，不需要安装依赖。

```bash
python3 src/arena_monitor.py check
```

首次运行会：

- 获取 5 类榜单的官方最新 Overall 数据；
- 保存不可变快照和 `data/latest.json`；
- 生成当前 Top 10 的基线概览；
- 不发送“变化”邮件，因为尚无上一版可比。

第二次及以后运行会：

- 官方数据没有变化：不写新快照，不生成简报；
- 数据有变化但未命中 4 类事件：只更新快照；
- 命中事件：在 `reports/` 生成 Markdown 和 HTML 简报；
- 加上 `--send-email`：在命中事件时发送邮件；
- 加上 `--send-feishu`：在命中事件时发送飞书消息卡片。

## 定时运行

监控程序不依赖常驻服务，可由 cron、systemd timer、GitHub Actions 或其他调度器
每天调用。以北京时间每天 09:00 运行为例：

```bash
0 1 * * * cd /path/to/arena-monitor-v1 && python3 src/arena_monitor.py check --send-email
```

首次基线、无新数据或只有普通名次变化时，不会生成变化简报；采集或通知失败会明确
报错，不会伪装成“无变化”。

## 飞书通知

飞书通知可通过自定义机器人接入。Webhook 通过环境变量或仓库 Secret
`ARENA_FEISHU_WEBHOOK_URL` 注入，不会出现在代码、日志、快照或 Git 历史中。

有重要变化时，飞书会收到一张按榜单分组的消息卡片，包含：

- 发生变化的榜单和数据发布日期；
- 模型名称及变化前后排名；
- Arena 原榜单链接；
- 本次命中的事件数量。

无变化、只有普通排名波动或首次建立基线时，不发送飞书消息。本地环境配置好
`ARENA_FEISHU_WEBHOOK_URL` 后可以执行：

```bash
python3 src/arena_monitor.py test-feishu
python3 src/arena_monitor.py check --send-feishu
```

## 独立 SMTP 方式（可选）

使用程序内置的 SMTP 发信时，可将 `.env.example` 中的变量配置到本机环境或
GitHub Actions Secrets。必填项：

- `ARENA_SMTP_HOST`
- `ARENA_SMTP_PORT`
- `ARENA_SMTP_SECURITY`：`starttls`、`ssl` 或 `none`
- `ARENA_SMTP_USERNAME`
- `ARENA_SMTP_PASSWORD`
- `ARENA_MAIL_FROM`
- `ARENA_MAIL_TO`

例如 Gmail SMTP 需要开启两步验证并使用 App Password，不应使用账户主密码。环境变量准备好后运行：

```bash
python3 src/arena_monitor.py check --send-email
```

## GitHub Actions 方式（可选）

`.github/workflows/arena-monitor.yml` 已配置为北京时间每天 09:00 检查一次，也支持手动触发。它会把历史快照和生成的简报提交回当前仓库，因此仓库的 Actions 需要有写入权限。

使用时：

1. 将项目提交到 GitHub 仓库。
2. 在仓库 Secrets 中添加 `ARENA_FEISHU_WEBHOOK_URL`；如果还需要 SMTP 邮件，再添加上述邮件变量。
3. 手动运行一次 workflow，建立初始基线。
4. 之后每天自动检查；无重要变化时不发邮件。

## 模型改名

V1 默认用规范化后的模型名称识别同一模型。若官方改名，可在 `config/model_aliases.json` 添加别名，避免被误判为“一删一增”：

```json
{
  "旧名称": "统一模型标识",
  "新名称": "统一模型标识"
}
```

## 数据来源

- [Arena 官方榜单](https://arena.ai/leaderboard)
- [Arena 官方 Hugging Face 历史榜单数据集](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset)
- [Arena Leaderboard Changelog](https://arena.ai/blog/leaderboard-changelog/)
