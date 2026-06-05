"""github-watch check script — run by the github-watch skill.

Moved out of SKILL.md's inline heredoc so the agent runs it with a one-line command
(python3 <this file>) instead of echoing the whole script into its tool call every run,
which kept the scheduled task's context heavy. Behaviour is identical to the inline version.
"""
import json, os, sys, time, subprocess, datetime, concurrent.futures

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

_TRANSIENT = ("502", "503", "504", "timeout", "timed out", "gateway",
              "couldn't respond", "try again", "temporarily", "connection reset")

def gh_json(args, retries=2):
    # GitHub's API (esp. the GraphQL endpoint behind issue/pr list) occasionally returns a
    # transient 5xx/timeout. Retry those a couple of times with backoff before giving up, so a
    # blip doesn't surface as a per-repo error.
    last = "gh error"
    for attempt in range(retries + 1):
        r = subprocess.run(["gh"] + args, capture_output=True, text=True)
        if r.returncode == 0:
            return json.loads(r.stdout or "[]")
        last = (r.stderr or "gh error").strip()
        if attempt < retries and any(t in last.lower() for t in _TRANSIENT):
            time.sleep(1.5 * (attempt + 1))
            continue
        break
    raise RuntimeError(last)

def read_secret(key):
    # A0 Secrets store: usr/secrets.env, "KEY=value" (value may be quoted). Same file gh auth reads.
    paths = []
    try:
        from helpers import files
        paths.append(files.get_abs_path("usr", "secrets.env"))
    except Exception:
        pass
    paths.append("/a0/usr/secrets.env")
    for p in paths:
        try:
            if p and os.path.isfile(p):
                with open(p, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line.startswith(key + "="):
                            v = line.split("=", 1)[1].strip()
                            if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
                                v = v[1:-1]
                            return v
        except Exception:
            continue
    return ""

def tg_html(md):
    # Minimal Markdown -> Telegram-HTML so direct-mode messages read as nicely as the tool path:
    # tables become aligned monospace <pre> blocks; headings and **bold** become <b>; [text](url)
    # links render. Stdlib only; raw URLs auto-link in Telegram's HTML mode.
    import html as _h, re as _re
    tables = []
    def _conv(m):
        rows = []
        for tl in m.group(0).strip().split("\n"):
            tl = tl.strip()
            if not tl.startswith("|"):
                continue
            if _re.match(r"^\|[\s\-:|]+\|$", tl):   # skip the |---|---| separator row
                continue
            rows.append([c.strip() for c in tl.split("|")[1:-1]])
        if not rows:
            return m.group(0)
        ncol = max(len(r) for r in rows)
        w = [0] * ncol
        for r in rows:
            for i, c in enumerate(r):
                if i < ncol:
                    w[i] = max(w[i], len(c))
        lines = []
        for ri, r in enumerate(rows):
            lines.append(" | ".join((r[i] if i < len(r) else "").ljust(w[i]) for i in range(ncol)))
            if ri == 0:
                lines.append("-+-".join("-" * x for x in w))
        tables.append("\n".join(lines))
        return f"\x00T{len(tables) - 1}\x00"
    md = _re.sub(r"(?:^\|.+\|$\n?)+", _conv, md, flags=_re.MULTILINE)

    # Pull blockquote "cards" (runs of lines starting with '>') out before escaping, so each becomes a
    # single Telegram <blockquote> (Style A). A blank line separates one card from the next.
    quotes = []
    def _conv_q(m):
        inner = [_re.sub(r"^>\s?", "", ql) for ql in m.group(0).rstrip("\n").split("\n")]
        quotes.append("\n".join(inner))
        return f"\x00Q{len(quotes) - 1}\x00"
    md = _re.sub(r"(?:^>.*$\n?)+", _conv_q, md, flags=_re.MULTILINE)

    def _inline(s):
        s = _h.escape(s)
        s = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        s = _re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        return s

    md = _h.escape(md)
    md = _re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", md, flags=_re.MULTILINE)
    md = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", md)
    md = _re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', md)
    for i, q in enumerate(quotes):
        md = md.replace(f"\x00Q{i}\x00", f"<blockquote>{_inline(q)}</blockquote>")
    for i, t in enumerate(tables):
        md = md.replace(f"\x00T{i}\x00", f"<pre>{_h.escape(t)}</pre>")
    return md

def telegram_direct(cfg, report):
    # Self-contained Telegram delivery: this plugin sends the report itself via the Bot API,
    # with no dependency on any other plugin. Best-effort; notes go to stderr so the relayed
    # report (stdout) stays verbatim.
    import urllib.request, urllib.parse, urllib.error
    key = str(cfg.get("telegram_secret_key", "TELEGRAM_BOT_TOKEN") or "TELEGRAM_BOT_TOKEN").strip()
    token = read_secret(key)
    chat_id = str(cfg.get("telegram_chat_id", "") or "").strip()
    if not token or not chat_id:
        miss = "bot token" if not token else "chat id"
        sys.stderr.write(f"[github-watch] Telegram (direct) on but no {miss} configured - skipped. "
                         f"Add the '{key}' Secret and set telegram_chat_id.\n")
        return
    # Telegram caps a message at 4096 chars; split the markdown on line boundaries (HTML tags add
    # length, so leave headroom). Each chunk is converted to HTML independently so tags never split.
    chunks, cur = [], ""
    for line in report.split("\n"):
        if cur and len(cur) + len(line) + 1 > 3500:
            chunks.append(cur); cur = line
        else:
            cur = (cur + "\n" + line) if cur else line
    if cur:
        chunks.append(cur)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for ch in chunks:
        # Prefer the nicely-formatted HTML; if Telegram rejects it (400), retry the chunk as plain text.
        try:
            attempts = [(tg_html(ch), "HTML"), (ch, None)]
        except Exception:
            attempts = [(ch, None)]
        sent = False
        for body, pm in attempts:
            fields = {"chat_id": chat_id, "text": body, "disable_web_page_preview": "true"}
            if pm:
                fields["parse_mode"] = pm
            data = urllib.parse.urlencode(fields).encode()
            try:
                with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as resp:
                    resp.read()
                sent = True
                break
            except urllib.error.HTTPError as e:
                if e.code == 400 and pm:        # malformed HTML -> fall back to plain text
                    continue
                body_err = e.read().decode("utf-8", "replace")[:200]
                sys.stderr.write(f"[github-watch] Telegram send failed ({e.code}): {body_err}\n")
                return
            except Exception as e:
                sys.stderr.write(f"[github-watch] Telegram send error: {e}\n")
                return
        if not sent:
            sys.stderr.write("[github-watch] Telegram send failed (HTML and plain both rejected).\n")
            return
    sys.stderr.write(f"[github-watch] Telegram (direct) sent to {chat_id}.\n")

cfg = load_cfg()
want_commits = bool(cfg.get("watch_commits", False))
want_enrich = bool(cfg.get("watch_enrich", False))
repos = set(norm_repos(cfg))
if cfg.get("watch_include_subscriptions", True):
    # Only repos watched at "All Activity" level are returned here; Custom/Participating watches
    # are not exposed by GitHub's API. Reading this needs the token's "Watching: Read" permission.
    sub = subprocess.run(["gh","api","user/subscriptions","--paginate","-q",".[].full_name"],
                         capture_output=True, text=True)
    if sub.returncode == 0:
        repos.update(r.strip() for r in sub.stdout.splitlines() if r.strip())
    else:
        # Don't fail the whole watch — fall back to watch_repos and note why (note -> stderr so the
        # relayed report stays clean). A fine-grained PAT most often just needs Watching: Read.
        sys.stderr.write("[github-watch] couldn't read GitHub-Watched repos (using watch_repos only): "
                         + (sub.stderr or "").strip()[:200]
                         + " — a fine-grained token needs the 'Watching: Read' account permission.\n")
repos = sorted(repos)

os.makedirs(os.path.dirname(STATE), exist_ok=True)
state = json.load(open(STATE)) if os.path.exists(STATE) else {"last_checked": {}}
state.setdefault("last_checked", {})
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")

now_h = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

# Fields to fetch per item. Enrichment pulls body/labels/author so the report can show more detail.
_ITEM_FIELDS = "number,title,url,state" + (",body,labels,author" if want_enrich else "")

def _snippet(text, n=200):
    # Collapse whitespace to one line (so a body's own headings/tables can't trigger the HTML
    # converter) and drop ** bold markers so arbitrary body text renders literally.
    text = " ".join((text or "").split()).replace("**", "")
    return (text[:n].rstrip() + "…") if len(text) > n else text

def _card(kind, item):
    """One issue/PR as a Style-A blockquote 'card' when enrichment is on, else a one-line bullet.
    No folder/avatar images (Telegram can't embed them) — author shows as '@login' text only."""
    emoji, label = {"issue": ("🐛", "Issue"), "pr": ("🔀", "PR")}[kind]
    num, title, url, state = item["number"], item["title"], item["url"], item["state"]
    if not want_enrich:
        return f"- {emoji} {label} #{num} {title} ({state}) — {url}"
    lines = [f"> **{emoji} {label} [#{num}]({url}) · {state}**", f"> {title}"]
    meta = []
    author = (item.get("author") or {}).get("login")
    if author:
        meta.append(f"👤 @{author}")
    labels = [l.get("name") for l in (item.get("labels") or []) if l.get("name")]
    if labels:
        meta.append("🏷 " + ", ".join(labels))
    if meta:
        lines.append("> " + " · ".join(meta))
    body = _snippet(item.get("body"))
    if body:
        lines.append(f"> {body}")
    return "\n".join(lines)

def check_repo(repo, ts):
    """One repo's check; runs in a worker thread. Returns (status, detail|None, count, stamp_ok)."""
    if not ts:                                   # first sight: baseline only, no backlog dump
        return ("🆕 baseline set", None, 0, True)
    try:
        issues = gh_json(["issue","list","--repo",repo,"--state","all","--search",
                          f"updated:>={ts}","--json",_ITEM_FIELDS,"--limit","50"])
        prs = gh_json(["pr","list","--repo",repo,"--state","all","--search",
                       f"updated:>={ts}","--json",_ITEM_FIELDS,"--limit","50"])
        commits = gh_json(["api", f"repos/{repo}/commits?since={ts}"]) if want_commits else []
    except Exception as e:                       # leave ts unchanged so nothing is missed
        return ("⚠️ error", f"**{repo}** — error: {e}", 0, False)
    parts = []
    if issues:  parts.append("🐛 " + plural(len(issues), "issue"))
    if prs:     parts.append("🔀 " + plural(len(prs), "PR"))
    if commits: parts.append("📝 " + plural(len(commits), "commit"))
    n = len(issues) + len(prs) + len(commits)
    if not n:
        return ("✅ nothing new", None, 0, True)
    cards = [_card("issue", i) for i in issues] + [_card("pr", p) for p in prs]
    for c in commits:
        sha = (c.get("sha") or "")[:7]
        cm = c.get("commit") or {}
        msg = (cm.get("message") or "").split("\n")[0]
        url = c.get("html_url", "")
        if not want_enrich:
            cards.append(f"- 📝 commit `{sha}` {msg} — {url}")
            continue
        clines = [f"> **📝 Commit [{sha}]({url})**", f"> {msg}"]
        author = (cm.get("author") or {}).get("name") or (c.get("author") or {}).get("login")
        if author:
            clines.append(f"> 👤 {author}")
        cards.append("\n".join(clines))
    # Enriched cards are blockquotes -> blank line between each so they don't merge into one;
    # plain bullets pack tight under the repo header.
    if want_enrich:
        detail = f"**{repo}**\n\n" + "\n\n".join(cards)
    else:
        detail = f"**{repo}**\n" + "\n".join(cards)
    return (" · ".join(parts), detail, n, True)

# Check every repo concurrently; assemble results in sorted repo order so output stays deterministic.
checked = {}
if repos:
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(repos))) as ex:
        futs = {ex.submit(check_repo, r, state["last_checked"].get(r)): r for r in repos}
        for fut in concurrent.futures.as_completed(futs):
            checked[futs[fut]] = fut.result()

rows, details, new_count, err_count = [], [], 0, 0
for repo in repos:
    status, detail, count, stamp_ok = checked[repo]
    rows.append((repo, status))
    if detail:
        details.append(detail)
    new_count += count
    if stamp_ok:
        state["last_checked"][repo] = now        # advance only after a successful check
    else:
        err_count += 1                           # stamp_ok is False only when the check errored

json.dump(state, open(STATE, "w"), indent=2)

# Final, presentation-ready markdown report (relay this verbatim).
head = f"## GitHub Watch — {new_count} new"
if err_count:
    head += f", {err_count} error" + ("" if err_count == 1 else "s")
head += f" across {plural(len(repos), 'repo')} · {now_h}"
out = [head, "",
       "| Repo | Status |", "|---|---|"]
out += [f"| {repo} | {status} |" for repo, status in rows]
if details:
    out += ["", "### New activity"]
    for d in details:
        out += ["", d]
report = "\n".join(out)

# Self-contained delivery: when telegram_method is "direct" and there is new activity, this
# plugin sends the report to Telegram itself (no other plugin needed). "tool" mode instead
# leaves Telegram to the scheduled task's agent (it calls a Telegram send tool if it has one).
if (new_count or err_count) and bool(cfg.get("watch_notify_telegram", False)) \
        and str(cfg.get("telegram_method", "tool")).strip().lower() == "direct":
    telegram_direct(cfg, report)

# Enrichment (extension method): leave a digest request for the github enrich extension, which runs
# right after this script and calls the chosen model to post a release-note digest to the toast.
# Gated on the in-app toggle, since the digest IS the in-app notification when enrichment is on.
if (new_count or err_count) and want_enrich and bool(cfg.get("watch_notify_chat", True)) \
        and str(cfg.get("enrich_method", "extension")).strip().lower() == "extension":
    try:
        json.dump({
            "model": str(cfg.get("enrich_model", "utility")).strip().lower(),
            "new_count": new_count, "err_count": err_count,
            "activity": "\n\n".join(details), "ts": now,
        }, open(os.path.join(os.path.dirname(STATE), "pending_digest.json"), "w"), indent=2)
    except Exception as e:
        sys.stderr.write(f"[github-watch] couldn't queue digest: {e}\n")

print(report)
