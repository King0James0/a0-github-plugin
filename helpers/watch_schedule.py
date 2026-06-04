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


def _cron(cfg: dict):
    """Build a TaskSchedule from watch_interval_hours (default 1 = hourly at :00)."""
    from helpers.task_scheduler import TaskSchedule

    try:
        hours = int(cfg.get("watch_interval_hours", 1) or 1)
    except (TypeError, ValueError):
        hours = 1
    hours = max(1, min(hours, 24))
    hour_field = "*" if hours == 1 else f"*/{hours}"
    return TaskSchedule(minute="0", hour=hour_field, day="*", month="*", weekday="*")


def _prompt(cfg: dict) -> str:
    base = (
        "Run the github-watch skill: check every watched repo for issues and pull "
        "requests that are new or updated since the last check, then update the "
        "last-checked timestamps. "
    )
    parts = []
    if bool(cfg.get("watch_notify_chat", True)):
        parts.append("Report the results in this conversation.")
    if bool(cfg.get("watch_notify_telegram", False)):
        parts.append(
            "If there is anything new, send a short summary to me on Telegram "
            "(send nothing if nothing is new)."
        )
    other = str(cfg.get("watch_notify_other", "") or "").strip()
    if other:
        parts.append(f"Also deliver the results per this instruction: {other}")
    if not parts:
        parts.append("Report the results in this conversation.")
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
            _log(f"watch schedule updated ('{TASK_NAME}', {schedule.to_crontab()})")
        else:
            task = ScheduledTask.create(
                name=TASK_NAME,
                system_prompt=SYSTEM_PROMPT,
                prompt=prompt,
                schedule=schedule,
            )
            await scheduler.add_task(task)
            _log(f"watch schedule created ('{TASK_NAME}', {schedule.to_crontab()})")

    asyncio.run(_go())


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
