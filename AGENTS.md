# AGENTS.md — operating contract for `a0-github-plugin`

You are working on an Agent Zero plugin that gives the agent real GitHub powers through the `gh` CLI,
authenticated from the user's GitHub token. A mistake here writes that token to disk where it can leak
into a shipped artifact or a backup, installs a tampered binary, opens PRs against the wrong repo, or
wedges the user's boot / save / uninstall. Follow these rules exactly. They are not suggestions.

## What this plugin is
A self-contained A0 plugin (id `github`): it installs the `gh` CLI into its own folder, authenticates
it **statelessly** from an A0 Secret, and ships a pack of process **skills** (`github-open-pr`,
`github-triage-issue`, `github-review-pr`, `github-search`, `github-watch`, `github-create-release`)
whose tested `gh` command templates teach the agent the *workflow*, not just the tool. It also
self-registers an optional hourly `github-watch` scheduled task. Publishable (MIT), model-agnostic,
uninstall-clean. The surface: a `gh`/`git` auth wrapper + the skills + a few extensions + one config UI.

## HARD INVARIANTS — never violate
1. **Auth is STATELESS — the token is NEVER persisted.** It lives only in A0 Secrets (`usr/secrets.env`,
   key from `secret_key`, default `GITHUB_TOKEN`) and is read fresh per operation by the
   `/usr/local/bin/gh` wrapper (`gh_setup.ensure_wrapper`), which exports it as `GH_TOKEN` for that one
   `gh` process. NEVER write it to a `gh` login file, a git credential store, an env file, or a log.
   `git` transport uses the SAME wrapper via the single `credential.https://github.com.helper` line —
   never a stored credential.
2. **Verify the binary before you trust it.** `gh_setup.ensure_binary` downloads `gh` and MUST pass
   `_verify_checksum` against GitHub's published `gh_<ver>_checksums.txt` SHA-256 before install. A
   checksum mismatch or missing entry REFUSES the install — never relax or skip this.
3. **Touch nothing outside the plugin folder except the two things you remove on uninstall.** The only
   external state this plugin creates is the `/usr/local/bin/gh` wrapper and that one `github.com` git
   credential-helper line. `gh_setup.cleanup()` (called by `uninstall()` in `hooks.py`) must remove
   EXACTLY those; `watch_schedule.remove()` removes the scheduled task. Add a new external side effect →
   add its reversal in the same change. Runtime state stays under `usr/github-watch/`.
4. **Every entry point is best-effort — never block boot, save, or uninstall.** All of `gh_setup` and
   `watch_schedule` log-and-return on error, never raise. The `startup_migration` extensions, the
   `save_plugin_config` hook, and the uninstall path each tolerate a failure of any other. A setup
   failure must degrade to "GitHub unavailable," never a crashed container.
5. **Self-registered cron must be VALID — never emit `*/24`.** `watch_schedule._cron` maps an interval
   token / custom cron to a `TaskSchedule`; an N≥24h cadence becomes a fixed daily run (`minute=0
   hour=0`) because `*/24` is an invalid hour step (max 23) that crash-loops the scheduler. A custom
   `watch_cron` is gated by `_cron_ok` (must be a 5-field crontab) before use.
6. **The watch context reset runs at `monologue_START`, not end.** Scheduler-driven runs never set
   `context.task`, so A0 never fires `monologue_end` / `message_loop_end` for them — only
   `monologue_start` fires. `_80_github_reset` rebuilds history to ONLY the current run's message
   (gated on the watch context id + `watch_reset_context`), bounding the reused task context so it can't
   grow until it exceeds the model window. Don't move this logic to an end hook — it would never fire.
7. **Delivery tools must fire BEFORE `response`.** Calling `response` ends the task (break_loop)
   instantly, so any agent-owned delivery (notify_user, telegram_send) must run first. The
   `watch_schedule._prompt` builder emits a STRICT-ORDER block ONLY when the agent owns a delivery call;
   direct-mode Telegram (sent by `check.py`) and the extension digest must instead tell the agent NOT to
   send, or it double-delivers. Keep these mutually exclusive.
8. **The watch runs check.py exactly once per cycle.** `tool_execute_before/_30_github_watch_once`
   blocks a weak utility model from re-running `check.py` within one scheduled run (RepairableException;
   keyed on the run's `last_user_message.id` so it self-resets each cycle; scoped to the watch context
   so a manual run is unaffected). `helpers/run_once.py` holds the sys-attached state. The task is named
   "GitHub Watch" (renamed from the pre-1.5.6 "github-watch-poll", migrated in place on reconcile).

## Build discipline
- **Stdlib-only helpers, A0 reached lazily.** `helpers/gh_setup.py` + `helpers/watch_schedule.py` import
  A0 (`from helpers ...`, `from usr.plugins.github ...`) only INSIDE functions, behind try/except, so a
  partial framework never breaks import. `skills/github-watch/check.py` is stdlib-only (+ optional `gh`).
- **Per change:** `py_compile` every `.py` via `/opt/venv-a0/bin/python -m py_compile`; keep skill
  command templates tested and `default_config.yaml` ↔ `webui/config.html` keys in sync. Bump
  `plugin.yaml` `version` on a release, and cut a tagged GitHub Release with user-facing notes.
- **Keep THIS file current.** Update this AGENTS.md in the SAME change whenever you alter a HARD INVARIANT, a cited path/seam/A0 mechanic, or what this plugin is — a stale contract MISLEADS (worse than none). Routine fixes/features that don't change the contract don't touch it.
- **Validate in a THROWAWAY, never the live instance.** Snapshot/commit the A0 instance into an isolated
  container and verify there (auth wrapper writes, checksum path, schedule reconcile, config render in a
  real browser). The maintainer installs the built artifact via the UX — don't live-install.
- **Opsec (public repo):** no secrets, tokens, IPs, internal hostnames, personal email, or local paths in
  shipped files. `config.json`, `.toggle-*`, `bin/`, `dist/`, `__pycache__/` are gitignored (and
  `CLAUDE.md` / `.claude/` if ever added — dev-only). Commits: single human author, GitHub no-reply
  email, NO AI / `Co-Authored-By` trailers.

## Knowledge map (one source of truth each — never duplicate)
- **Structure, setup, auth model, config keys, uninstall:** `README.md`.
- **Config defaults + inline rationale:** `default_config.yaml` (the canonical key list + meanings).
- **Process / workflow:** the per-ability `skills/*/SKILL.md` (the tested `gh` command templates — the
  agent's source of truth for *how* to do each GitHub task; `github-watch/check.py` is the poll script).
- **Authoring conventions** (this whole plugin framework): the `a0-plugin-template` `AUTHORING.md`.
  (This repo has no `ARCHITECTURE.md` or GitNexus index — README + skills + config are the SoT.)

## Verified A0 mechanics (don't re-derive — confirm against the LIVE instance; versions move constantly)
- Hooks: `startup_migration/_50` (`gh_setup.ensure()` each boot — reinstalls wrapper) · `_60`
  (`watch_schedule.ensure()` reconciles the task) · `monologue_start/_80` (watch context reset) ·
  `tool_execute_after/_60` (enrich digest, consumes `pending_digest.json` once) · the
  `get_chat_model/end/_50` reroute (utility-tier swap for agent-mode enrich) · `hooks.py`
  `install/uninstall/save_plugin_config`.
- `plugins.get_plugin_config(name)` returns the saved `config.json` **OR** defaults — **NEVER merged**.
  `_config()` falls back to `default_config.yaml`, so a fresh install still works; but to add a key to a
  live install you must save the COMPLETE dict or the others drop.
- Scheduler: `scheduler.add_task()` is the public path that BOTH appends the task AND creates its
  context (required — the Tasks list classifies contexts by id via `state_snapshot`). The reused task
  context's agent grows history every run unless reset (see invariant 6). `save_plugin_config` runs
  BEFORE the new config is written, so reconcile from the incoming `settings`. `check_schedule()` is a
  STATELESS ~60s cron window (no `last_run` catch-up — setting it is a no-op for cron tasks; `job_loop`
  ticks 60s); `find_task_by_name` is a SUBSTRING match (probe full names).
- Secrets: read at call time from `usr/secrets.env` (`KEY=value`, value may be quoted) by the wrapper,
  by `check.py` (direct Telegram), and by `gh` natively via `GH_TOKEN` — never from a stored login.
