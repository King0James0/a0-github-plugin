---
name: github-watch
description: Poll watched GitHub repos for new or updated issues and pull requests since the last check, and manage the watch list. Use when the user asks to watch/track/monitor a repo, check for new issues or PRs, see what's new on GitHub, or add/remove/show watched repos. Assumes the github plugin has authenticated gh.
---

# Watch GitHub repos for new issues and PRs

Reports issues and pull requests that are **new or updated since the last check** across a combined
set of repositories — and, when `watch_commits` is enabled, new **commits** on each repo's default
branch too. Individual comments are not a separate scope (but a comment bumps its issue/PR's
`updatedAt`, so it surfaces under that item).

## The watched set

The repos to check are the **union** of two sources (deduplicated):

1. **The configured list** — `watch_repos` in the plugin config, edited in the plugin's **Config**
   panel (one `owner/name` per line). This is the authoritative list; it lives in the plugin config,
   not a runtime file.
2. **GitHub-watched repos** — repos the user Watches on GitHub (notification subscriptions), pulled
   live with `gh api user/subscriptions --paginate -q '.[].full_name'`. Included only when
   `watch_include_subscriptions` is true. Note: *Watched* ≠ *Starred*.

Config is read from `/a0/usr/plugins/github/config.json` (the saved config the Config panel writes),
falling back to `/a0/usr/plugins/github/default_config.yaml` before the first save. Only the per-repo
**last-checked timestamps** live in a runtime file: `/a0/usr/github-watch/watch_state.json`.

## Check for new activity (the main job)

The plugin ships the check as a script file. Run it **verbatim, in one command** (below) — do not
paste or reconstruct the script inline. It does the whole job deterministically — resolves the watched
set, checks issues + PRs + (when enabled) commits for **every repo in parallel** (a thread pool) since
each repo's own `last_checked`, prints a grouped report, and advances the timestamps. Do NOT hand-run
per-repo `gh` commands instead; the point of one script is that no step (especially commits) gets
skipped and the checks run concurrently. Then deliver the printed report per the user's notify
settings.

```bash
python3 /a0/usr/plugins/github/skills/github-watch/check.py
```

The script prints a **finished markdown report**. Relay it to the user **exactly as printed** —
character for character, **including every emoji** (🐛 🔀 📝 ✅ 🆕 ⚠️). Do not summarize, reword,
reformat, or replace any emoji with words. When there are new items **or any repo shows a ⚠️ error**,
call the **`notify_user`** tool **exactly once** (toast + notifications bell) with that **exact** report
text — no token needed; do not call it more than once. (Transient errors already auto-retried; a ⚠️ row
means it persisted and is worth a heads-up.)

Telegram: the script handles it **itself** when `telegram_method` is `direct` (it already sent the
report via the Bot API by the time you see it — do not send it again). When `telegram_method` is
`tool`, send the same report yourself **if you have a Telegram send tool** (e.g. the YATCA
`telegram_send` tool) whenever there are new items **or a ⚠️ error**; if you have no such tool, skip
Telegram. Never hand-run per-repo `gh` commands.

Notes: the commits leg covers each repo's **default branch** only (the API takes `sha=<branch>` for
others) and `since` filters by commit date, so a force-push or a merge of older commits may not
surface. A repo's first appearance records a baseline and reports nothing (no backlog flood).

## Manage the watch list (writes the plugin config so it shows in the Config panel)

The list lives in `watch_repos` in the plugin config. To keep the Config panel as the single source
of truth, add/remove by editing `config.json` in place — preserving every other config key. If
`config.json` doesn't exist yet, seed it from `default_config.yaml` so no defaults are lost (config is
loaded whole, not merged).

Add (when the user says "watch owner/name"):
```bash
python3 - "owner/name" <<'PY'
import json, os, sys
PLUGIN_DIR = "/a0/usr/plugins/github"
cj = os.path.join(PLUGIN_DIR, "config.json")

def base():
    if os.path.exists(cj):
        try:
            return json.load(open(cj))
        except Exception:
            pass
    try:
        import yaml
        return yaml.safe_load(open(os.path.join(PLUGIN_DIR, "default_config.yaml"))) or {}
    except Exception:
        return {}

def norm(raw):
    if isinstance(raw, str):
        raw = [p for line in raw.splitlines() for p in line.split(",")]
    return [r.strip() for r in (raw or []) if isinstance(r, str) and r.strip()]

repo = sys.argv[1].strip()
cfg = base()
repos = norm(cfg.get("watch_repos"))
if repo not in repos:
    repos.append(repo)
cfg["watch_repos"] = "\n".join(repos)   # newline string = one-per-line in the Config textarea
json.dump(cfg, open(cj, "w"), indent=2)
print("watching:", repo)
PY
```
This edits only the **configured list** — it does not Star or Watch the repo on GitHub.

Remove ("unwatch owner/name"): same as above but `repos = [r for r in repos if r != repo]`.

Show the current watched set (config list ∪ subscriptions): reuse the resolve snippet above.

## Recurring polling

This skill is the *what to check*. The plugin can run it for you on a schedule: in the Config panel
turn **Recurring poll** on (`watch_schedule_enabled: true`) and it self-registers an A0 scheduled task
(`GitHub Watch`) that runs this skill every `watch_interval_hours` (default hourly) and delivers
new findings per the `watch_notify` pointer (`chat` / `telegram` / `seekerzero`). Turning it off or
uninstalling removes the task. The skill itself only reports into the conversation; the scheduled task
owns cadence + delivery via A0's own channels — this skill does not send anything.

## Rules

- Scope is issues + PRs always, plus commits when `watch_commits` is on. If the user asks about
  individual comments, note they surface via the parent issue/PR's `updatedAt`; the raw feed is
  `gh api "repos/<REPO>/issues/comments?since=<TS>"`.
- Always update `last_checked` after a successful check, or the next run repeats the same items.
- On the very first run for a repo, stamp it and report nothing for it (no backlog flood).
- Keep timestamps in UTC ISO-8601 (`...Z`); GitHub's `updated:>=` search qualifier expects that.

## Failure handling

- `gh: command not found` -> the plugin's gh setup did not run; reinstall/re-enable the github plugin.
- Auth/permission error (`403 Resource not accessible by personal access token`) -> the `GITHUB_TOKEN`
  Secret is missing or under-scoped (needs `repo` classic, or Issues + Pull requests read on fine-grained;
  `read:org` for org repos). Tell the user to update it under Settings > External Services > Secrets. Do
  NOT run `gh auth login` — this plugin authenticates from the Secret.
- Empty watched set -> the config list is empty and you Watch no repos on GitHub; ask the user to add
  repos in the plugin's Config panel (or say "watch owner/name"). (Reminder: Star and Watch are
  different buttons on GitHub; the auto-source reads Watch, not Star.)
