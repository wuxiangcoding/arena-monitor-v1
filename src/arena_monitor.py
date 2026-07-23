#!/usr/bin/env python3
"""Arena five-leaderboard monitor.

The monitor reads Arena's official historical leaderboard dataset on Hugging
Face, stores immutable snapshots, compares the current data with the last
snapshot, and reports only the four event types selected for V1.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import smtplib
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Iterable


DATASET = "lmarena-ai/leaderboard-dataset"
DATASET_API = "https://datasets-server.huggingface.co/filter"
DATASET_PAGE = "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset"

BOARDS: dict[str, dict[str, str]] = {
    "text": {
        "label": "Text",
        "subset": "text_style_control",
        "url": "https://arena.ai/leaderboard/text",
    },
    "agent": {
        "label": "Agent",
        "subset": "agent",
        "url": "https://arena.ai/leaderboard/agent",
    },
    "webdev": {
        "label": "WebDev",
        "subset": "webdev",
        "url": "https://arena.ai/leaderboard/code/webdev",
    },
    "text-to-image": {
        "label": "Text-to-Image",
        "subset": "text_to_image",
        "url": "https://arena.ai/leaderboard/text-to-image",
    },
    "image-edit": {
        "label": "Image Edit",
        "subset": "image_edit",
        "url": "https://arena.ai/leaderboard/image-edit",
    },
}

EVENT_LABELS = {
    "added": "新模型进入榜单",
    "removed": "模型从榜单消失",
    "leader_changed": "榜首变化",
    "entered_top": "进入 Top 区间",
    "left_top": "跌出 Top 区间",
}


@dataclass(frozen=True)
class ChangeEvent:
    board: str
    kind: str
    model: str | None = None
    old_rank: int | None = None
    new_rank: int | None = None
    boundary: int | None = None
    old_leaders: tuple[str, ...] = ()
    new_leaders: tuple[str, ...] = ()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_name(name: str) -> str:
    return " ".join(name.casefold().strip().split())


def load_aliases(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("别名文件必须是 JSON 对象")
    aliases: dict[str, str] = {}
    for alias, canonical in raw.items():
        aliases[normalize_name(str(alias))] = normalize_name(str(canonical))
    return aliases


def model_key(name: str, aliases: dict[str, str]) -> str:
    normalized = normalize_name(name)
    return aliases.get(normalized, normalized)


def request_json(url: str, retries: int = 3) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "arena-monitor-v1/1.0",
        },
    )
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    raise RuntimeError(f"请求 Arena 官方数据失败：{last_error}") from last_error


def fetch_board(
    board_slug: str,
    request: Callable[[str], dict[str, Any]] = request_json,
) -> dict[str, Any]:
    definition = BOARDS[board_slug]
    offset = 0
    page_size = 100
    entries: list[dict[str, Any]] = []

    while True:
        query = urllib.parse.urlencode(
            {
                "dataset": DATASET,
                "config": definition["subset"],
                "split": "latest",
                "where": '"category"=\'overall\'',
                "orderby": '"rank"',
                "offset": offset,
                "length": page_size,
            }
        )
        payload = request(f"{DATASET_API}?{query}")
        page = [item["row"] for item in payload.get("rows", [])]
        entries.extend(page)
        total = int(payload.get("num_rows_total", len(entries)))
        offset += len(page)
        if not page or offset >= total:
            break

    if not entries:
        raise RuntimeError(f"{definition['label']} 没有返回 overall 数据")

    entries.sort(key=lambda item: (int(item["rank"]), str(item["model_name"]).casefold()))
    publish_dates = sorted(
        {str(item["leaderboard_publish_date"]) for item in entries if item.get("leaderboard_publish_date")}
    )
    return {
        "label": definition["label"],
        "subset": definition["subset"],
        "url": definition["url"],
        "category": "overall",
        "publish_date": publish_dates[-1] if publish_dates else None,
        "entries": entries,
    }


def fetch_all_boards() -> dict[str, dict[str, Any]]:
    return {slug: fetch_board(slug) for slug in BOARDS}


def content_hash(boards: dict[str, dict[str, Any]]) -> str:
    canonical = json.dumps(boards, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def make_snapshot(boards: dict[str, dict[str, Any]], fetched_at: datetime) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fetched_at": iso_utc(fetched_at),
        "source": DATASET_PAGE,
        "content_hash": content_hash(boards),
        "boards": boards,
    }


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_snapshot(snapshot: dict[str, Any], data_dir: Path) -> Path:
    timestamp = snapshot["fetched_at"].replace(":", "").replace("-", "")
    short_hash = snapshot["content_hash"][:10]
    snapshot_path = data_dir / "snapshots" / f"{timestamp}-{short_hash}.json"
    write_json(snapshot_path, snapshot)
    write_json(data_dir / "latest.json", snapshot)
    return snapshot_path


def indexed_entries(
    board: dict[str, Any],
    aliases: dict[str, str],
) -> dict[str, dict[str, Any]]:
    return {model_key(str(entry["model_name"]), aliases): entry for entry in board["entries"]}


def names_at_rank(entries: Iterable[dict[str, Any]], rank: int) -> tuple[str, ...]:
    return tuple(sorted(str(entry["model_name"]) for entry in entries if int(entry["rank"]) == rank))


def detect_board_changes(
    board_slug: str,
    previous: dict[str, Any],
    current: dict[str, Any],
    aliases: dict[str, str] | None = None,
) -> list[ChangeEvent]:
    aliases = aliases or {}
    old_by_key = indexed_entries(previous, aliases)
    new_by_key = indexed_entries(current, aliases)
    old_keys = set(old_by_key)
    new_keys = set(new_by_key)
    events: list[ChangeEvent] = []

    for key in sorted(new_keys - old_keys):
        entry = new_by_key[key]
        events.append(
            ChangeEvent(
                board=board_slug,
                kind="added",
                model=str(entry["model_name"]),
                new_rank=int(entry["rank"]),
            )
        )

    for key in sorted(old_keys - new_keys):
        entry = old_by_key[key]
        events.append(
            ChangeEvent(
                board=board_slug,
                kind="removed",
                model=str(entry["model_name"]),
                old_rank=int(entry["rank"]),
            )
        )

    old_leaders = names_at_rank(old_by_key.values(), 1)
    new_leaders = names_at_rank(new_by_key.values(), 1)
    if old_leaders != new_leaders:
        events.append(
            ChangeEvent(
                board=board_slug,
                kind="leader_changed",
                old_leaders=old_leaders,
                new_leaders=new_leaders,
            )
        )

    for boundary in (3, 10):
        for key in sorted(old_keys & new_keys):
            old_entry = old_by_key[key]
            new_entry = new_by_key[key]
            old_rank = int(old_entry["rank"])
            new_rank = int(new_entry["rank"])
            if old_rank > boundary >= new_rank:
                events.append(
                    ChangeEvent(
                        board=board_slug,
                        kind="entered_top",
                        model=str(new_entry["model_name"]),
                        old_rank=old_rank,
                        new_rank=new_rank,
                        boundary=boundary,
                    )
                )
            elif old_rank <= boundary < new_rank:
                events.append(
                    ChangeEvent(
                        board=board_slug,
                        kind="left_top",
                        model=str(new_entry["model_name"]),
                        old_rank=old_rank,
                        new_rank=new_rank,
                        boundary=boundary,
                    )
                )

    return events


def detect_changes(
    previous_snapshot: dict[str, Any],
    current_snapshot: dict[str, Any],
    aliases: dict[str, str] | None = None,
) -> list[ChangeEvent]:
    aliases = aliases or {}
    events: list[ChangeEvent] = []
    for slug in BOARDS:
        old_board = previous_snapshot["boards"].get(slug)
        new_board = current_snapshot["boards"].get(slug)
        if old_board is None or new_board is None:
            continue
        events.extend(detect_board_changes(slug, old_board, new_board, aliases))
    return events


def event_text(event: ChangeEvent) -> str:
    if event.kind == "added":
        return f"新增 **{event.model}**，当前第 {event.new_rank} 名"
    if event.kind == "removed":
        return f"**{event.model}** 从榜单消失，上期第 {event.old_rank} 名"
    if event.kind == "leader_changed":
        old = "、".join(event.old_leaders) or "无"
        new = "、".join(event.new_leaders) or "无"
        return f"榜首由 **{old}** 变为 **{new}**"
    direction = "进入" if event.kind == "entered_top" else "跌出"
    return (
        f"**{event.model}** {direction} Top {event.boundary}"
        f"（{event.old_rank} → {event.new_rank}）"
    )


def report_markdown(
    events: list[ChangeEvent],
    current_snapshot: dict[str, Any],
    previous_snapshot: dict[str, Any],
) -> str:
    changed_boards = {event.board for event in events}
    lines = [
        "# Arena 榜单变动简报",
        "",
        f"- 检查时间：{current_snapshot['fetched_at']}",
        f"- 对比基线：{previous_snapshot['fetched_at']}",
        f"- 监控范围：{len(BOARDS)} 个一级榜单的 Overall",
        f"- 结果：{len(changed_boards)} 个榜单，共 {len(events)} 项重要变化",
        "",
        "只包含：新模型、模型消失、榜首变化、进入/跌出 Top 3 或 Top 10。",
        "",
    ]

    for slug, definition in BOARDS.items():
        board_events = [event for event in events if event.board == slug]
        if not board_events:
            continue
        publish_date = current_snapshot["boards"][slug].get("publish_date") or "未知"
        lines.extend(
            [
                f"## {definition['label']}",
                "",
                f"数据发布日期：{publish_date} · [查看 Arena 原榜单]({definition['url']})",
                "",
            ]
        )
        for event in board_events:
            lines.append(f"- {event_text(event)}")
        lines.append("")

    lines.extend(
        [
            "## 说明",
            "",
            "- “消失”不等同于“弃用”；只有 Arena 官方变更日志明确说明时，才应标记为弃用。",
            f"- 数据源：[Arena 官方 Hugging Face 榜单数据集]({DATASET_PAGE})。",
            "- 普通名次波动、分数变化和票数增长不在 V1 通知范围内。",
            "",
        ]
    )
    return "\n".join(lines)


def baseline_markdown(snapshot: dict[str, Any]) -> str:
    lines = [
        "# Arena 榜单监控 V1：初始基线",
        "",
        f"- 建立时间：{snapshot['fetched_at']}",
        "- 范围：Text、Agent、WebDev、Text-to-Image、Image Edit",
        "- 分类：仅 Overall",
        "- 说明：这是首次快照，不代表发生了榜单变化；下一次运行才开始生成差异简报。",
        "",
    ]
    for slug, definition in BOARDS.items():
        board = snapshot["boards"][slug]
        lines.extend(
            [
                f"## {definition['label']}",
                "",
                f"数据发布日期：{board.get('publish_date') or '未知'} · [查看榜单]({definition['url']})",
                "",
                "| 排名 | 模型 | 机构 |",
                "|---:|---|---|",
            ]
        )
        for entry in board["entries"]:
            if int(entry["rank"]) > 10:
                continue
            model = str(entry["model_name"]).replace("|", "\\|")
            organization = str(entry.get("organization") or "—").replace("|", "\\|")
            lines.append(f"| {entry['rank']} | {model} | {organization} |")
        lines.append("")
    return "\n".join(lines)


def markdown_to_email_html(
    events: list[ChangeEvent],
    current_snapshot: dict[str, Any],
    previous_snapshot: dict[str, Any],
) -> str:
    sections: list[str] = []
    for slug, definition in BOARDS.items():
        board_events = [event for event in events if event.board == slug]
        if not board_events:
            continue
        items = "".join(
            f"<li style='margin:8px 0'>{html.escape(event_text(event)).replace('**', '')}</li>"
            for event in board_events
        )
        publish_date = html.escape(str(current_snapshot["boards"][slug].get("publish_date") or "未知"))
        sections.append(
            "<section style='margin:24px 0'>"
            f"<h2 style='font-size:20px;margin:0 0 8px'>{html.escape(definition['label'])}</h2>"
            f"<p style='color:#667085;margin:0 0 8px'>数据发布日期：{publish_date} · "
            f"<a href='{html.escape(definition['url'])}'>查看原榜单</a></p>"
            f"<ul style='padding-left:22px;margin:0'>{items}</ul>"
            "</section>"
        )
    return (
        "<!doctype html><html><body style='margin:0;background:#f6f7f9'>"
        "<div style='max-width:680px;margin:0 auto;padding:32px 20px;font-family:"
        "-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#101828'>"
        "<div style='background:white;border:1px solid #eaecf0;border-radius:16px;padding:28px'>"
        "<h1 style='font-size:26px;margin:0 0 10px'>Arena 榜单变动简报</h1>"
        f"<p style='color:#475467;margin:0'>{len(events)} 项重要变化 · "
        f"{html.escape(current_snapshot['fetched_at'])}</p>"
        f"{''.join(sections)}"
        "<hr style='border:0;border-top:1px solid #eaecf0;margin:24px 0'>"
        "<p style='font-size:13px;color:#667085;line-height:1.6;margin:0'>"
        "V1 只通知新模型、模型消失、榜首变化、进入/跌出 Top 3 或 Top 10。"
        "“消失”只有在官方明确说明后才会被认定为“弃用”。</p>"
        "</div></div></body></html>"
    )


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"发送邮件缺少环境变量：{name}")
    return value


def send_email(subject: str, markdown_body: str, html_body: str) -> None:
    host = require_env("ARENA_SMTP_HOST")
    port = int(os.environ.get("ARENA_SMTP_PORT", "587"))
    username = require_env("ARENA_SMTP_USERNAME")
    password = require_env("ARENA_SMTP_PASSWORD")
    sender = require_env("ARENA_MAIL_FROM")
    recipient = require_env("ARENA_MAIL_TO")
    security = os.environ.get("ARENA_SMTP_SECURITY", "starttls").strip().casefold()

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(markdown_body)
    message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, context=context, timeout=60) as server:
            server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=60) as server:
            server.ehlo()
            if security == "starttls":
                server.starttls(context=context)
                server.ehlo()
            server.login(username, password)
            server.send_message(message)


def run_check(args: argparse.Namespace) -> int:
    now = utc_now()
    data_dir = Path(args.data_dir)
    report_dir = Path(args.report_dir)
    aliases = load_aliases(Path(args.aliases) if args.aliases else None)
    previous = load_json(data_dir / "latest.json")
    current = make_snapshot(fetch_all_boards(), now)

    if previous and previous.get("content_hash") == current["content_hash"]:
        print("Arena 5 类榜单没有发布新数据；未生成简报。")
        return 0

    snapshot_path = save_snapshot(current, data_dir)
    if previous is None:
        baseline = baseline_markdown(current)
        report_path = report_dir / f"baseline-{now.date().isoformat()}.md"
        atomic_write_text(report_path, baseline)
        print(f"已建立首次基线：{snapshot_path}")
        print(f"已生成基线概览：{report_path}")
        return 0

    events = detect_changes(previous, current, aliases)
    if not events:
        print(f"榜单数据已更新并保存：{snapshot_path}")
        print("没有命中 V1 的 4 类重要变化；未生成简报。")
        return 0

    markdown = report_markdown(events, current, previous)
    html_body = markdown_to_email_html(events, current, previous)
    report_stem = f"arena-digest-{now.date().isoformat()}-{current['content_hash'][:8]}"
    markdown_path = report_dir / f"{report_stem}.md"
    html_path = report_dir / f"{report_stem}.html"
    atomic_write_text(markdown_path, markdown)
    atomic_write_text(html_path, html_body)

    if args.send_email:
        changed_board_count = len({event.board for event in events})
        subject = f"[Arena 榜单] {now.date().isoformat()}：{changed_board_count} 类榜单有重要变化"
        send_email(subject, markdown, html_body)
        print(f"邮件已发送，共 {len(events)} 项重要变化。")
    else:
        print("检测到重要变化；未启用邮件发送。")
    print(f"Markdown 简报：{markdown_path}")
    print(f"HTML 简报：{html_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Arena 五类榜单监控 V1")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("check",),
        default="check",
        help="拉取、对比并按需生成简报",
    )
    parser.add_argument("--data-dir", default="data", help="快照目录")
    parser.add_argument("--report-dir", default="reports", help="简报目录")
    parser.add_argument("--aliases", default="config/model_aliases.json", help="模型别名 JSON")
    parser.add_argument("--send-email", action="store_true", help="检测到变化时通过 SMTP 发信")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return run_check(args)
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
