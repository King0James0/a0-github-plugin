"""Self-register the github-watch poll as an A0 ScheduledTask.

Runs inside the Agent Zero framework runtime. The plugin OWNS the scheduled
task's existence: it reads its own config and reconciles a single ScheduledTask
named TASK_NAME — created/updated when watch_schedule_enabled is true, removed
when false or on uninstall.

The watched repo list is plain plugin config (watch_repos), edited in the
Config panel; this module does not manage that list. All entry points are
best-effort: they log and return rather than raising, so a failure never blocks
startup, save, or uninstall.

Separation of concerns (see README): the plugin decides *when* to poll and
*where to send* via a thin pointer (watch_notify, injected into the task
prompt). It does NOT implement delivery — the scheduled task runs in a full
agent context and uses A0's own channels (Telegram, etc.).
"""

from __future__ import annotations

import asyncio
import os
import re
import threading

PLUGIN_NAME = "github"
TASK_NAME = "github-watch-poll"

SYSTEM_PROMPT = (
    "You are a GitHub watch agent. Use the github-watch skill to report only what "
    "changed. Be terse: list new/updated issues and PRs grouped by repo, or say "
    "there is nothing new."
)


def _log(msg: str) -> None:
    try:
        from helpers.print_style import PrintStyle

        PrintStyle(font_color="cyan").print(f"[github plugin] {msg}")
    except Exception:
        print(f"[github plugin] {msg}")


def _config() -> dict:
    """Merged plugin config, falling back to default_config.yaml."""
    try:
        from helpers import plugins

        cfg = plugins.get_plugin_config(PLUGIN_NAME)
        if isinstance(cfg, dict):
            return cfg
    except Exception:
        pass
    try:
        from helpers import files, yaml as yaml_helper

        path = os.path.join(
            files.get_abs_path("usr", "plugins", PLUGIN_NAME), "default_config.yaml"
        )
        if files.exists(path):
            loaded = yaml_helper.loads(files.read_file(path))
            if isinstance(loaded, dict):
                return loaded
    except Exception:
        pass
    return {}


def _cron_ok(expr: str) -> bool:
    """True if expr is a valid 5-field crontab the scheduler can use."""
    try:
        from crontab import CronTab

        CronTab(crontab=expr)
        return len(expr.split()) == 5
    except Exception:
        return False


def _cron(cfg: dict):
    """Build a TaskSchedule. Precedence: a custom cron (watch_cron) wins; else a preset
    interval token (watch_interval like '15m' / '2h'); else legacy watch_interval_hours."""
    from helpers.task_scheduler import TaskSchedule

    custom = str(cfg.get("watch_cron", "") or "").strip()
    if custom:
        if _cron_ok(custom):
            f = custom.split()
            return TaskSchedule(minute=f[0], hour=f[1], day=f[2], month=f[3], weekday=f[4])
        _log(f"ignoring invalid watch_cron {custom!r}; using watch_interval instead")

    token = str(cfg.get("watch_interval", "") or "").strip().lower()
    if not token:  # back-compat with the old hours-only key
        try:
            token = f"{max(1, min(int(cfg.get('watch_interval_hours', 1) or 1), 24))}h"
        except (TypeError, ValueError):
            token = "1h"

    minute, hour = "0", "*"
    m = re.fullmatch(r"(\d+)\s*([mh])", token)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        if unit == "m":
            n = max(1, min(n, 59))
            minute, hour = (f"*/{n}" if n > 1 else "*"), "*"
        else:
            n = max(1, min(n, 24))
            if n >= 24:
                minute, hour = "0", "0"  # daily; */24 is invalid cron (hour step max 23)
            else:
                minute, hour = "0", (f"*/{n}" if n > 1 else "*")
    return TaskSchedule(minute=minute, hour=hour, day="*", month="*", weekday="*")


def _prompt(cfg: dict) -> str:
    base = (
        "Run the github-watch skill exactly as written (the single check script), then relay its "
        "printed markdown report EXACTLY as printed — character for character, INCLUDING every "
        "emoji (\U0001f41b \U0001f500 \U0001f4dd ✅ \U0001f195 ⚠️). Do not summarize, "
        "reword, reformat, or replace any emoji with words. "
    )
    notify_user = (
        'If the report shows any new items OR any repo with a ⚠️ error, call the notify_user tool '
        'EXACTLY ONCE with that EXACT report text (title "GitHub watch", type "success") so it appears as '
        "a toast and in the notifications bell — keep the emoji exactly as printed. Do not call notify_user "
        "more than once. If there are no new items and no errors, do not notify at all."
    )
    enrich = bool(cfg.get("watch_enrich", False))
    enrich_method = str(cfg.get("enrich_method", "extension") or "extension").strip().lower()
    extension_digest = enrich and enrich_method == "extension"
    agent_digest = enrich and enrich_method == "agent"

    parts = []
    required_calls = []  # tools the agent itself must call BEFORE `response`, in order
    if bool(cfg.get("watch_notify_chat", True)):
        if extension_digest:
            # The enrich extension posts a release-note digest to the in-app toast automatically;
            # the agent must NOT also call notify_user (that would double the toast).
            parts.append(
                "Do NOT call the notify_user tool — a release-note digest is posted to the in-app "
                "toast automatically. Just relay the full report as your reply."
            )
        elif agent_digest:
            parts.append(
                "Also write a SHORT release-note digest of what changed: group by repo, cite each item "
                "by #number or commit sha, use ONLY facts from the report, invent nothing. Then call the "
                'notify_user tool EXACTLY ONCE with JUST that digest (title "GitHub watch", type '
                '"success") — the digest, NOT the full report (the full report still goes in your reply). '
                "If there are no new items and no errors, do not notify."
            )
            required_calls.append("call notify_user once with the digest")
        else:
            parts.append(notify_user)
            required_calls.append("call notify_user once with the exact report")
    if bool(cfg.get("watch_notify_telegram", False)):
        method = str(cfg.get("telegram_method", "tool") or "tool").strip().lower()
        if method == "direct":
            # The watch script sends Telegram itself in direct mode; the agent must NOT also send.
            parts.append(
                "IMPORTANT — Telegram is ALREADY SENT by the script (direct mode): you MUST NOT call "
                "telegram_send or any Telegram-sending tool, even if the report text mentions Telegram. "
                "Calling it would deliver a duplicate. Do not send any Telegram message yourself under "
                "any circumstances."
            )
        else:
            bot = str(cfg.get("telegram_bot", "") or "").strip()
            which = f' Use the Telegram bot named "{bot}".' if bot else " Use the default Telegram bot."
            parts.append(
                "Also, when there are new items OR any repo errored (⚠️), send the same EXACT report to "
                "me on Telegram using your Telegram send tool (e.g. the telegram_send tool)." + which +
                " If you genuinely have no Telegram send tool, skip Telegram."
            )
            required_calls.append(
                f'call the telegram_send tool (bot "{bot}")' if bot else "call the telegram_send tool"
            )
    other = str(cfg.get("watch_notify_other", "") or "").strip()
    if other:
        parts.append(f"Also deliver the report per this instruction: {other}")
    if not parts:
        parts.append(notify_user)
        required_calls.append("call notify_user once with the exact report")

    # STRICT ORDER — `response` ends the task the instant it's called (break_loop), so any delivery the
    # agent must do itself has to happen FIRST or it never runs. Only added when the agent actually owns
    # one or more delivery calls (direct Telegram + extension digest need none — script/extension do it).
    if required_calls:
        seq = "; ".join(f"({i}) {c}" for i, c in enumerate(required_calls, 1))
        parts.append(
            "STRICT ORDER — the `response` tool ENDS the task the instant you call it, so it MUST be your "
            "VERY LAST action. When the report has any new items or a ⚠️ error, then BEFORE you call "
            f"`response` you MUST first, in this order: {seq}. Make every one of those tool calls and let "
            "each return FIRST — only then call `response` to relay the full report. Never call `response` "
            "before them: if you relay the report first, the task ends and nothing is sent. (If there are "
            "no new items and no errors, there is nothing to send — just relay the report.)"
        )
    return base + " ".join(parts)


def _reconcile_sync(cfg: dict) -> None:
    """Create/update/remove the scheduled task to match config."""
    enabled = bool(cfg.get("watch_schedule_enabled", False))

    async def _go():
        from helpers.task_scheduler import TaskScheduler, ScheduledTask

        scheduler = TaskScheduler.get()
        await scheduler.reload()
        existing = scheduler.find_task_by_name(TASK_NAME)

        if not enabled:
            if existing:
                await scheduler.remove_task_by_name(TASK_NAME)
                _log(f"watch schedule disabled — removed task '{TASK_NAME}'")
            return

        schedule = _cron(cfg)
        prompt = _prompt(cfg)
        if existing:
            existing[0].update(
                schedule=schedule, prompt=prompt, system_prompt=SYSTEM_PROMPT
            )
            await scheduler.save()
            the_task = existing[0]
            _log(f"watch schedule updated ('{TASK_NAME}', {schedule.to_crontab()})")
        else:
            task = ScheduledTask.create(
                name=TASK_NAME,
                system_prompt=SYSTEM_PROMPT,
                prompt=prompt,
                schedule=schedule,
            )
            # Register via the public path: scheduler.add_task() both appends the task AND creates its
            # dedicated context. The context is REQUIRED for the task to appear under Tasks — the state
            # snapshot builds the Tasks list by iterating contexts (AgentContext.all()) and classifying
            # any whose id matches a registered task as a task context (helpers/state_snapshot.py). A
            # registered scheduled-task context is shown under Tasks, never Chats, so this is correct and
            # does not clutter the chat list. (Deferring context creation hid the task from Tasks.)
            await scheduler.add_task(task)
            the_task = task
            _log(f"watch schedule created ('{TASK_NAME}', {schedule.to_crontab()})")

        # Persist the task's context id (= task uuid, set at create()) so the agent-mode model reroute
        # and the history-reset extensions can recognise this task's context when it runs.
        _write_context_id(getattr(the_task, "context_id", None))

    asyncio.run(_go())


def _write_context_id(ctx_id) -> None:
    if not ctx_id:
        return
    try:
        from helpers import files

        p = files.get_abs_path("usr", "github-watch", "task_context_id")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(str(ctx_id))
    except Exception as e:
        _log(f"couldn't persist watch context id: {e}")


def _remove_sync() -> None:
    async def _go():
        from helpers.task_scheduler import TaskScheduler

        scheduler = TaskScheduler.get()
        await scheduler.reload()
        if scheduler.find_task_by_name(TASK_NAME):
            await scheduler.remove_task_by_name(TASK_NAME)
            _log(f"removed task '{TASK_NAME}'")

    asyncio.run(_go())


def _spawn(target, block: bool) -> None:
    """Run an async-using sync routine in its own thread+loop (best-effort)."""

    def _run():
        try:
            target()
        except Exception as e:
            _log(f"watch schedule step failed: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    if block:
        t.join(timeout=30)


def ensure() -> None:
    """Reconcile the scheduled task from current config. Non-blocking (boot path)."""
    _spawn(lambda: _reconcile_sync(_config()), block=False)


def ensure_from(cfg: dict) -> None:
    """Reconcile using a config dict passed in (e.g. from the save hook, before disk write)."""
    if not isinstance(cfg, dict):
        return
    _spawn(lambda: _reconcile_sync(cfg), block=False)


def remove() -> None:
    """Remove the scheduled task. Blocking (uninstall must finish before removal)."""
    _spawn(_remove_sync, block=True)
