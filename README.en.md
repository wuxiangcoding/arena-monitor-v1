# Arena Five-Leaderboard Monitor V1

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md)

This is the first version distilled from the "Arena Leaderboard Analysis and
Monitoring" discussion. It checks five top-level Arena leaderboards every day
and generates a digest only when one of four high-value change types occurs.

## V1 Scope

| Category | Official data subset | Monitored category |
|---|---|---|
| Text | `text_style_control` | Overall |
| Agent | `agent` | Overall |
| WebDev | `webdev` | Overall |
| Text-to-Image | `text_to_image` | Overall |
| Image Edit | `image_edit` | Overall |

V1 only reports:

1. A new model entering a leaderboard
2. A model disappearing from a leaderboard
3. A change in the leader
4. Entering or leaving the Top 3 / Top 10

Ordinary rank changes, score changes, confidence-interval changes, and vote
growth are not reported. When a model disappears from a leaderboard, the digest
says only that it disappeared. It is not automatically classified as
"deprecated" unless Arena officially states that this is the case.

## Local Usage

The project uses only the Python standard library and has no dependencies.

```bash
python3 src/arena_monitor.py check
```

On the first run, the monitor:

- Fetches the latest official Overall data for all five leaderboards;
- Saves immutable snapshots and `data/latest.json`;
- Generates a baseline overview of the current Top 10;
- Does not send a change email because there is no previous version to compare.

On subsequent runs, the monitor:

- Does not write a new snapshot or generate a digest when the official data has
  not changed;
- Only updates the snapshot when the data changed but none of the four event
  types occurred;
- Generates Markdown and HTML digests in `reports/` when an event occurs;
- Sends email when a change occurs if `--send-email` is provided;
- Sends a Feishu interactive card when a change occurs if `--send-feishu` is
  provided.

## Currently Enabled Daily Task

The "**Arena Five-Leaderboard Daily Monitor**" task is enabled in Codex:

- It runs every day at 09:00 Beijing time;
- It runs the monitor from this directory;
- It sends mail through the connected Gmail account to the current account only
  when one of the four high-value change types occurs;
- It does not send mail for the initial baseline, unchanged data, or ordinary
  rank changes;
- Collection and notification failures are reported explicitly instead of
  being treated as "no changes."

## Feishu Notifications

GitHub Actions is connected to a Feishu custom bot. The webhook is injected
through the repository secret `ARENA_FEISHU_WEBHOOK_URL` and is not present in
the code, logs, snapshots, or Git history.

When an important change occurs, Feishu receives a card grouped by leaderboard
that contains:

- The affected leaderboard and data publication date;
- Model names and their rank before and after the change;
- A link to the original Arena leaderboard;
- The number of events in the update.

No Feishu message is sent when there are no changes, when only ordinary rank
changes occurred, or when the initial baseline is created. After configuring
`ARENA_FEISHU_WEBHOOK_URL` locally, run:

```bash
python3 src/arena_monitor.py test-feishu
python3 src/arena_monitor.py check --send-feishu
```

## Standalone SMTP Setup (Optional)

If you do not want to run the monitor through Codex in the future, you can use
the built-in SMTP sender. Copy the variables in `.env.example` into your local
environment or GitHub Actions Secrets. Required variables:

- `ARENA_SMTP_HOST`
- `ARENA_SMTP_PORT`
- `ARENA_SMTP_SECURITY`: `starttls`, `ssl`, or `none`
- `ARENA_SMTP_USERNAME`
- `ARENA_SMTP_PASSWORD`
- `ARENA_MAIL_FROM`
- `ARENA_MAIL_TO`

For example, Gmail SMTP requires two-step verification and an App Password. Do
not use the account's primary password. After configuring the environment
variables, run:

```bash
python3 src/arena_monitor.py check --send-email
```

## GitHub Actions Setup (Optional)

`.github/workflows/arena-monitor.yml` is configured to check once per day at
09:00 Beijing time and also supports manual runs. It commits historical
snapshots and generated digests back to the private repository, so repository
Actions must have write permission.

To use it:

1. Commit this directory to a private GitHub repository.
2. Add `ARENA_FEISHU_WEBHOOK_URL` to the repository Secrets. Add the SMTP
   variables above if email is also required.
3. Run the workflow manually once to create the initial baseline.
4. The workflow then checks daily and does not send mail when there are no
   important changes.

## Model Renames

By default, V1 identifies models by their normalized names. If a model is
officially renamed, add an alias in `config/model_aliases.json` to avoid
reporting it as one removal and one addition:

```json
{
  "Old Name": "Canonical Model Identifier",
  "New Name": "Canonical Model Identifier"
}
```

## Data Sources

- [Arena official leaderboards](https://arena.ai/leaderboard)
- [Arena official Hugging Face historical leaderboard dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset)
- [Arena Leaderboard Changelog](https://arena.ai/blog/leaderboard-changelog/)
