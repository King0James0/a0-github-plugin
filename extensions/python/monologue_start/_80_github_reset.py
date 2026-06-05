"""GitHub watch — reset the scheduled task's context at the START of each run.

The github-watch-poll task runs in ONE dedicated context (its id = the task uuid) and the scheduler
REUSES that context's agent every run (helpers/task_scheduler._run_task: `agent = context.agent0`),
appending the new task prompt to the SAME agent.history. Nothing trims it, so it grows every run until
it exceeds the model's context window (litellm ContextWindowExceededError).

This MUST run at monologue_START, not monologue_end. The scheduler never sets `context.task`, and A0
only fires `message_loop_end` / `monologue_end` extensions when `context.task and context.task.is_alive()`
(agent.py) — never true for scheduler-driven runs, so a monologue_end reset never executes. monologue_start
has no such guard, so it is the only loop hook that actually fires for a scheduled task.

By the time monologue_start fires, the scheduler has already appended THIS run's user message
(`agent.hist_add_user_message` in _run_task, before `agent.monologue()`). So we rebuild history to contain
ONLY that current message — dropping every prior run — which bounds the context to a single run.

Gated on the watch context id (written by watch_schedule.py) and the watch_reset_context toggle.
"""

import os

from helpers.extension import Extension

PLUGIN_NAME = "github"
_CTX_FILE = "usr/github-watch/task_context_id"


def _watch_ctx_id() -> str:
    try:
        from helpers import files
        p = files.get_abs_path(_CTX_FILE)
    except Exception:
        p = os.path.join("/a0", _CTX_FILE)
    try:
        return open(p, encoding="utf-8").read().strip() if os.path.isfile(p) else ""
    except Exception:
        return ""


class GithubWatchReset(Extension):

    async def execute(self, loop_data=None, **kwargs):
        agent = self.agent
        if not agent or getattr(agent, "number", 0) != 0:
            return
        ctx = getattr(agent, "context", None)
        watch_id = _watch_ctx_id()
        if not watch_id or not ctx or getattr(ctx, "id", None) != watch_id:
            return
        try:
            from helpers import plugins
            cfg = plugins.get_plugin_config(PLUGIN_NAME) or {}
        except Exception:
            cfg = {}
        if not bool(cfg.get("watch_reset_context", True)):
            return

        cur = getattr(agent, "last_user_message", None)
        if cur is None:
            # No current message to preserve — never blank a run that has no message yet.
            return
        try:
            # Fresh history holding ONLY this run's task message; every prior run is dropped. Uses the
            # public History.add_message so we don't depend on Topic/Bulk internals.
            new_hist = type(agent.history)(agent)
            msg = new_hist.add_message(
                getattr(cur, "ai", False), cur.content,
                tokens=getattr(cur, "tokens", 0), id=getattr(cur, "id", ""),
            )
            agent.history = new_hist
            agent.last_user_message = msg
            if loop_data is not None:
                loop_data.user_message = msg
            # Keep the visible chat log bounded too (separate store from history); best-effort.
            try:
                ctx.log.reset()
            except Exception:
                pass
        except Exception as e:
            try:
                from helpers.print_style import PrintStyle
                PrintStyle(font_color="cyan").print(f"[github plugin] context reset failed: {e}")
            except Exception:
                pass
