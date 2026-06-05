"""GitHub watch — enrichment digest (extension method).

After the github-watch script runs (a code_execution), it may leave a pending_digest.json. This
extension consumes it, calls the configured model tier (utility|chat) to write a short release-note
digest of what changed, and posts that digest to the in-app toast (notify_user) only. Chat + Telegram
keep the full report. Deterministic: the model is called from code, not left to the agent.

Only active when enrichment is on with enrich_method = extension (the script only writes the request
in that case). Best-effort throughout — a failure never disrupts the watch.
"""

import os
import json

from helpers.extension import Extension

PLUGIN_NAME = "github"
_DIGEST_FILE = "usr/github-watch/pending_digest.json"

_SYSTEM = (
    "You write a short release-note digest of GitHub activity for a developer. "
    "Summarize what changed in plain language, grouped by repo where it helps. "
    "Cite each item by its number (#N) or commit sha. Use ONLY the facts given below — do not invent "
    "anything, add no opinions or next steps. If any repo failed to check, note it in one line. "
    "Keep it to a few short lines. Output only the digest text, no preamble."
)


def _digest_path():
    try:
        from helpers import files
        return files.get_abs_path(_DIGEST_FILE)
    except Exception:
        return os.path.join("/a0", _DIGEST_FILE)


class GithubEnrichDigest(Extension):

    async def execute(self, tool_name: str = "", **kwargs):
        if tool_name != "code_execution_tool" or not self.agent:
            return
        path = _digest_path()
        if not os.path.isfile(path):
            return
        # Consume the request exactly once: read then remove, so a re-run or a stale file can't
        # post twice and an unrelated later code_execution won't pick it up.
        try:
            req = json.loads(open(path, encoding="utf-8").read())
        except Exception:
            req = None
        try:
            os.remove(path)
        except Exception:
            pass
        if not isinstance(req, dict):
            return

        activity = (req.get("activity") or "").strip()
        if not activity:
            return
        tier = str(req.get("model", "utility")).strip().lower()

        try:
            model = self.agent.get_chat_model() if tier == "chat" else self.agent.get_utility_model()
            if model is None:
                return
            counts = f"{req.get('new_count', 0)} new"
            if req.get("err_count"):
                counts += f", {req['err_count']} error(s)"
            message = f"GitHub activity ({counts}):\n\n{activity}"
            resp, _reasoning = await model.unified_call(system_message=_SYSTEM, user_message=message)
            digest = (resp or "").strip()
        except Exception as e:
            self._log(f"digest model call failed: {e}")
            return
        if not digest:
            return

        try:
            from agent import AgentContext
            from helpers.notification import NotificationType, NotificationPriority
            AgentContext.get_notification_manager().add_notification(
                message=digest,
                title="GitHub watch",
                type=NotificationType.SUCCESS,
                priority=NotificationPriority.HIGH,
                display_time=30,
            )
        except Exception as e:
            self._log(f"digest notify failed: {e}")

    def _log(self, msg: str) -> None:
        try:
            from helpers.print_style import PrintStyle
            PrintStyle(font_color="cyan").print(f"[github plugin] {msg}")
        except Exception:
            print(f"[github plugin] {msg}")
