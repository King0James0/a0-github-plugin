"""GitHub watch — agent-mode model reroute.

When enrichment runs with enrich_method = agent and enrich_model = utility, the whole github-watch-poll
task should run on the utility tier (so the agent writes the digest on the chosen model). This end
extension runs after _model_config has set the chat model and, ONLY for the watch task's context,
swaps the result to the utility model.

It is a no-op for every other context, for extension mode, when enrichment is off, and when the
chosen tier is already chat. The watch context id is written by watch_schedule.py at reconcile time.
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


class GithubEnrichReroute(Extension):
    def execute(self, data: dict = {}, **kwargs):
        agent = self.agent
        if not agent or not isinstance(data, dict):
            return
        ctx = getattr(agent, "context", None)
        watch_id = _watch_ctx_id()
        if not watch_id or not ctx or getattr(ctx, "id", None) != watch_id:
            return
        try:
            from helpers import plugins
            cfg = plugins.get_plugin_config(PLUGIN_NAME) or {}
        except Exception:
            return
        if not cfg.get("watch_enrich"):
            return
        if str(cfg.get("enrich_method", "extension")).strip().lower() != "agent":
            return
        if str(cfg.get("enrich_model", "utility")).strip().lower() != "utility":
            return  # chat tier is already the default chat model; nothing to swap
        try:
            util = agent.get_utility_model()
        except Exception:
            util = None
        if util is not None:
            data["result"] = util
