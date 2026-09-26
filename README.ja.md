# Arena 5部門リーダーボード監視 V1

[简体中文](README.md) | [English](README.en.md) | [日本語](README.ja.md)

これは「Arena リーダーボード分析と監視」の議論からまとめた初版です。毎日
Arena のトップレベル 5 部門を確認し、価値の高い 4 種類の変化が発生した場合に
のみダイジェストを生成します。

## V1 の対象範囲

| カテゴリ | 公式データ subset | 監視カテゴリ |
|---|---|---|
| Text | `text_style_control` | Overall |
| Agent | `agent` | Overall |
| WebDev | `webdev` | Overall |
| Text-to-Image | `text_to_image` | Overall |
| Image Edit | `image_edit` | Overall |

V1 が通知するのは次の 4 種類です。

1. 新しいモデルのランキング入り
2. モデルのランキングからの消滅
3. 首位の交代
4. Top 3 / Top 10 への進入または圏外転落

通常の順位変動、スコア変動、信頼区間の変化、投票数の増加は通知しません。
モデルがランキングから消えた場合、ダイジェストには「消滅」とのみ記載します。
Arena が公式に明示しない限り、自動的に「提供終了」とは判定しません。

## ローカル実行

このプロジェクトは Python 標準ライブラリのみを使用し、依存関係はありません。

```bash
python3 src/arena_monitor.py check
```

初回実行時:

- 5 部門すべての公式 Overall 最新データを取得します。
- 変更不可のスナップショットと `data/latest.json` を保存します。
- 現在の Top 10 のベースライン概要を生成します。
- 比較対象がないため、変化通知メールは送信しません。

2 回目以降の実行時:

- 公式データに変化がなければ、新しいスナップショットやダイジェストを生成しません。
- データは変化したものの 4 種類のイベントに該当しなければ、スナップショットだけを
  更新します。
- イベントに該当した場合、`reports/` に Markdown と HTML のダイジェストを生成します。
- `--send-email` を指定すると、変化の発生時にメールを送信します。
- `--send-feishu` を指定すると、変化の発生時に Feishu のインタラクティブカードを
  送信します。

## 現在有効な日次タスク

Codex では「**Arena 5部門リーダーボード日次監視**」が有効になっています。

- 北京時間の毎日 09:00 に実行されます。
- このディレクトリで監視プログラムを実行します。
- 価値の高い 4 種類の変化が発生した場合にのみ、接続済みの Gmail から現在の
  アカウント自身に送信します。
- 初回ベースライン、データ未更新、通常の順位変動だけの場合は送信しません。
- 取得または通知に失敗した場合は明示的にエラーを報告し、「変化なし」として
  扱いません。

## Feishu 通知

GitHub Actions は Feishu のカスタムボットに接続されています。Webhook は
リポジトリ Secret `ARENA_FEISHU_WEBHOOK_URL` から注入され、コード、ログ、
スナップショット、Git 履歴には含まれません。

重要な変化が発生すると、Feishu にはリーダーボード別に整理されたカードが届きます。
カードには次の情報が含まれます。

- 変化したリーダーボードとデータ公開日
- モデル名と変化前後の順位
- Arena の元のリーダーボードへのリンク
- 今回該当したイベント数

変化がない場合、通常の順位変動だけの場合、初回ベースラインの作成時は Feishu
メッセージを送信しません。ローカルで `ARENA_FEISHU_WEBHOOK_URL` を設定した後、
次のコマンドを実行できます。

```bash
python3 src/arena_monitor.py test-feishu
python3 src/arena_monitor.py check --send-feishu
```

## 独立した SMTP 設定（任意）

今後 Codex 経由で実行しない場合は、プログラム内蔵の SMTP 送信機能を利用できます。
`.env.example` の変数をローカル環境または GitHub Actions Secrets に設定してください。
必須項目:

- `ARENA_SMTP_HOST`
- `ARENA_SMTP_PORT`
- `ARENA_SMTP_SECURITY`: `starttls`、`ssl`、または `none`
- `ARENA_SMTP_USERNAME`
- `ARENA_SMTP_PASSWORD`
- `ARENA_MAIL_FROM`
- `ARENA_MAIL_TO`

たとえば Gmail SMTP では 2 段階認証を有効にして App Password を使用します。
アカウントのメインパスワードは使用しないでください。環境変数を設定した後、次を
実行します。

```bash
python3 src/arena_monitor.py check --send-email
```

## GitHub Actions の設定（任意）

`.github/workflows/arena-monitor.yml` は、北京時間の毎日 09:00 に 1 回確認し、
手動実行にも対応するよう設定されています。履歴スナップショットと生成した
ダイジェストをプライベートリポジトリへコミットして戻すため、リポジトリの
Actions には書き込み権限が必要です。

使用方法:

1. このディレクトリをプライベート GitHub リポジトリへコミットします。
2. リポジトリ Secret に `ARENA_FEISHU_WEBHOOK_URL` を追加します。メールも必要な
   場合は、上記の SMTP 変数も追加します。
3. workflow を手動で 1 回実行し、初期ベースラインを作成します。
4. 以降は毎日自動確認され、重要な変化がなければメールを送信しません。

## モデル名の変更

V1 は既定で正規化したモデル名を使って同一モデルを識別します。公式に名前が変更
された場合は、`config/model_aliases.json` に別名を追加すると、削除と追加に
分かれて誤判定されることを防げます。

```json
{
  "Old Name": "Canonical Model Identifier",
  "New Name": "Canonical Model Identifier"
}
```

## データソース

- [Arena 公式リーダーボード](https://arena.ai/leaderboard)
- [Arena 公式 Hugging Face 履歴リーダーボードデータセット](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset)
- [Arena Leaderboard Changelog](https://arena.ai/blog/leaderboard-changelog/)
