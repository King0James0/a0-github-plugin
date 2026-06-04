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

Run the **single script below, verbatim**. It does the whole job deterministically — resolves the
watched set, checks issues + PRs + (when enabled) commits for every repo since its own
`last_checked`, prints a grouped report, and advances the timestamps. Do NOT hand-run per-repo `gh`
commands instead; the point of one script is that no step (especially commits) gets skipped. Then
deliver the printed report per the user's notify settings.

```bash
python3 - <<'PY'
import json, os, subprocess, datetime

PLUGIN_DIR = "/a0/usr/plugins/github"
STATE = "/a0/usr/github-watch/watch_state.json"

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

def gh_json(args):
    r = subprocess.run(["gh"] + args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "gh error").strip())
    return json.loads(r.stdout or "[]")

cfg = load_cfg()
want_commits = bool(cfg.get("watch_commits", False))
repos = set(norm_repos(cfg))
if cfg.get("watch_include_subscriptions", True):
    try:
        out = subprocess.run(["gh","api","user/subscriptions","--paginate","-q",".[].full_name"],
                             capture_output=True, text=True, check=True).stdout
        repos.update(r.strip() for r in out.splitlines() if r.strip())
    except subprocess.CalledProcessError:
        pass
repos = sorted(repos)

os.makedirs(os.path.dirname(STATE), exist_ok=True)
state = json.load(open(STATE)) if os.path.exists(STATE) else {"last_checked": {}}
state.setdefault("last_checked", {})
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

report, new_count = [], 0
for repo in repos:
    ts = state["last_checked"].get(repo)
    if not ts:                                  # first sight: baseline only, no backlog dump
        state["last_checked"][repo] = now
        report.append(f"{repo}: first check — baseline recorded, nothing reported")
        continue
    try:
        issues = gh_json(["issue","list","--repo",repo,"--state","all","--search",
                          f"updated:>={ts}","--json","number,title,url,state","--limit","50"])
        prs = gh_json(["pr","list","--repo",repo,"--state","all","--search",
                       f"updated:>={ts}","--json","number,title,url,state","--limit","50"])
        commits = gh_json(["api", f"repos/{repo}/commits?since={ts}"]) if want_commits else []
    except Exception as e:                       # leave ts unchanged so nothing is missed
        report.append(f"{repo}: ERROR ({e}) — timestamp left unchanged")
        continue
    lines = [f"  issue #{i['number']} {i['title']} ({i['state']}) — {i['url']}" for i in issues]
    lines += [f"  PR #{p['number']} {p['title']} ({p['state']}) — {p['url']}" for p in prs]
    for c in commits:
        sha = (c.get("sha") or "")[:7]
        msg = ((c.get("commit") or {}).get("message") or "").split("\n")[0]
        lines.append(f"  commit {sha} {msg} — {c.get('html_url','')}")
    if lines:
        new_count += len(lines)
        report.append(f"{repo}:\n" + "\n".join(lines))
    else:
        report.append(f"{repo}: nothing new")
    state["last_checked"][repo] = now           # advance only after a successful check

json.dump(state, open(STATE, "w"), indent=2)
print(f"Checked {len(repos)} repo(s) since last check (commits={'on' if want_commits else 'off'}). New items: {new_count}\n")
print("\n".join(report))
PY
```

Then relay the report to the user per their notify settings (chat / Telegram / Other). Say "nothing
new" plainly when `New items: 0`. Do not re-run per-repo `gh` commands by hand.

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
