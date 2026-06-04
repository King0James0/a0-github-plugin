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

Resolve the watched set, then for each repo list issues and PRs updated since that repo's
`last_checked`, then record the new timestamp. Use UTC ISO-8601 timestamps.

```bash
# Resolve combined repo list (config list ∪ subscriptions), one owner/name per line, deduped:
python3 - <<'PY'
import json, os, subprocess
PLUGIN_DIR = "/a0/usr/plugins/github"

def load_cfg():
    cj = os.path.join(PLUGIN_DIR, "config.json")
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

def norm_repos(cfg):
    raw = cfg.get("watch_repos") or []
    if isinstance(raw, str):
        raw = [p for line in raw.splitlines() for p in line.split(",")]
    return [r.strip() for r in raw if isinstance(r, str) and r.strip()]

cfg = load_cfg()
repos = set(norm_repos(cfg))
if cfg.get("watch_include_subscriptions", True):
    try:
        out = subprocess.run(["gh","api","user/subscriptions","--paginate","-q",".[].full_name"],
                             capture_output=True, text=True, check=True).stdout
        repos.update(r.strip() for r in out.splitlines() if r.strip())
    except subprocess.CalledProcessError:
        pass
# scope flags the agent should honor for this run:
print("FLAGS", json.dumps({"commits": bool(cfg.get("watch_commits", False))}))
print("\n".join(sorted(repos)))
PY
```

Then per repo (substitute `<REPO>` and `<TS>` = that repo's last_checked from the state file, or skip
the `--search` filter on first sight):
```bash
gh issue list --repo <REPO> --state all --search "updated:>=<TS>" \
  --json number,title,url,updatedAt,state --limit 50
gh pr list    --repo <REPO> --state all --search "updated:>=<TS>" \
  --json number,title,url,updatedAt,state --limit 50
```

If the FLAGS line reported `"commits": true`, also list new commits on each repo's **default branch**
since `<TS>` (skip on first sight, same as above). A plain `git push` shows up here, not under issues/PRs.
```bash
gh api "repos/<REPO>/commits?since=<TS>" \
  -q '.[] | "  \(.sha[0:7]) \(.commit.message | split("\n")[0]) — \(.html_url)"'
```
Note: the GitHub commits API only covers the default branch (it takes `sha=<branch>` for others) and
`since` filters by commit date — a force-push or a merge of older commits may not surface.

After reporting, save the new timestamps to the runtime state file. First time a repo is seen (no
`last_checked` entry), record "now" and report nothing for it — this avoids dumping the whole backlog
on the first run.

```bash
# Stamp the given repos with the current UTC time in the state file:
python3 - "$@" <<'PY'
import json, os, datetime, sys
p = "/a0/usr/github-watch/watch_state.json"
os.makedirs(os.path.dirname(p), exist_ok=True)
state = json.load(open(p)) if os.path.exists(p) else {"last_checked": {}}
state.setdefault("last_checked", {})
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
for repo in sys.argv[1:]:
    state["last_checked"][repo] = now
json.dump(state, open(p, "w"), indent=2)
print("stamped", len(sys.argv[1:]), "repos @", now)
PY
# pass the checked repos as args, e.g.:  ... owner/name owner/other
```

Report format: group by repo, list `#<number> <title> (<state>) — <url>`. Say "nothing new" per repo
that had no updates. Do not dump raw JSON.

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
(`github-watch-poll`) that runs this skill every `watch_interval_hours` (default hourly) and delivers
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
