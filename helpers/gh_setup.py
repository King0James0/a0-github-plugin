"""Set up the gh CLI for the GitHub plugin with stateless, per-operation auth.

Runs inside the Agent Zero framework runtime. All entry points are best-effort:
they log and return rather than raising, so a setup failure never blocks startup.

Auth model (stateless — the token is never written to a gh/git credential store):
  - The token lives only in A0 Secrets (key from default_config, default GITHUB_TOKEN).
  - A thin /usr/local/bin/gh wrapper reads that token at call time, exports it as
    GH_TOKEN for that one process, and execs the real gh. gh uses GH_TOKEN for all
    GitHub API operations (PRs, issues, reviews, search).
  - git push/pull is routed through the same wrapper via a github.com-scoped
    credential helper (`gh auth git-credential`), so git transport uses the same
    token without it ever being stored.

Layout:
  <plugin>/bin/gh        downloaded gh binary (persisted; downloaded once)
  /usr/local/bin/gh      stateless auth wrapper (recreated each boot)
  global git config      one github.com credential.helper line (removed on uninstall)
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import stat
import subprocess
import tarfile
import urllib.request

PLUGIN_NAME = "github"
WRAPPER_PATH = "/usr/local/bin/gh"
GIT_CREDENTIAL_KEY = "credential.https://github.com.helper"
GIT_CREDENTIAL_VALUE = f"!{WRAPPER_PATH} auth git-credential"
_RELEASES_API = "https://api.github.com/repos/cli/cli/releases/latest"
_DOWNLOAD_BASE = "https://github.com/cli/cli/releases/download"
_UA = "agent-zero-github-plugin"


def _log(msg: str) -> None:
    try:
        from helpers.print_style import PrintStyle

        PrintStyle(font_color="cyan").print(f"[github plugin] {msg}")
    except Exception:
        print(f"[github plugin] {msg}")


def _plugin_dir() -> str:
    from helpers import files

    return files.get_abs_path("usr", "plugins", PLUGIN_NAME)


def _bin_path() -> str:
    return os.path.join(_plugin_dir(), "bin", "gh")


def _secrets_file() -> str:
    from helpers import files

    return files.get_abs_path("usr", "secrets.env")


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

        path = os.path.join(_plugin_dir(), "default_config.yaml")
        if files.exists(path):
            loaded = yaml_helper.loads(files.read_file(path))
            if isinstance(loaded, dict):
                return loaded
    except Exception:
        pass
    return {}


def _secret_key(cfg: dict | None = None) -> str:
    cfg = cfg if cfg is not None else _config()
    return cfg.get("secret_key") or "GITHUB_TOKEN"


def _gh_arch() -> str:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "amd64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    if m.startswith("armv6"):
        return "armv6"
    return "amd64"


def _resolve_version(cfg: dict) -> str | None:
    """Return a gh release tag like 'v2.63.2', or None if it can't be resolved."""
    ver = str(cfg.get("gh_version", "latest")).strip()
    if ver and ver.lower() != "latest":
        return ver if ver.startswith("v") else f"v{ver}"
    try:
        req = urllib.request.Request(_RELEASES_API, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        tag = data.get("tag_name")
        return tag or None
    except Exception as e:
        _log(f"could not resolve latest gh version: {e}")
        return None


def _verify_checksum(blob: bytes, tag: str, asset: str) -> bool:
    """Verify the downloaded asset against GitHub's published SHA-256 checksums file."""
    version = tag.lstrip("v")
    url = f"{_DOWNLOAD_BASE}/{tag}/gh_{version}_checksums.txt"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=60) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception as e:
        _log(f"could not fetch gh checksums: {e}")
        return False
    want = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].endswith(asset):
            want = parts[0].lower()
            break
    if not want:
        _log(f"no checksum entry for {asset}")
        return False
    got = hashlib.sha256(blob).hexdigest().lower()
    if got != want:
        _log(f"checksum mismatch for {asset}: expected {want[:12]}…, got {got[:12]}…")
        return False
    _log("gh download SHA-256 verified.")
    return True


def ensure_binary() -> bool:
    """Download gh into <plugin>/bin/gh if not already present. Returns True if available."""
    bin_path = _bin_path()
    if os.path.exists(bin_path) and os.access(bin_path, os.X_OK):
        return True

    cfg = _config()
    tag = _resolve_version(cfg)
    if not tag:
        return False
    version = tag.lstrip("v")
    arch = _gh_arch()
    asset = f"gh_{version}_linux_{arch}.tar.gz"
    url = f"{_DOWNLOAD_BASE}/{tag}/{asset}"

    try:
        _log(f"downloading gh {tag} ({arch})...")
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=120) as resp:
            blob = resp.read()
        # supply-chain hardening: verify against GitHub's published SHA-256 before trusting the binary
        if not _verify_checksum(blob, tag, asset):
            _log("gh download failed SHA-256 verification — refusing to install")
            return False
        member_suffix = f"gh_{version}_linux_{arch}/bin/gh"
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            src = None
            for m in tf.getmembers():
                if m.name.endswith(member_suffix) and m.isfile():
                    src = tf.extractfile(m)
                    break
            if src is None:
                _log(f"gh binary not found inside {asset}")
                return False
            os.makedirs(os.path.dirname(bin_path), exist_ok=True)
            with open(bin_path, "wb") as out:
                out.write(src.read())
        os.chmod(bin_path, 0o755)
        _log(f"installed gh {tag} -> {bin_path}")
        return True
    except Exception as e:
        _log(f"gh download failed: {e}")
        return False


def ensure_wrapper() -> bool:
    """Write the stateless /usr/local/bin/gh wrapper. Recreated each boot.

    The wrapper reads the token from A0 Secrets at call time and exports it as
    GH_TOKEN for that single gh process. If a token is already present in the
    environment, it is respected and not overwritten.
    """
    bin_path = _bin_path()
    secrets_file = _secrets_file()
    key = _secret_key()
    script = (
        "#!/bin/sh\n"
        "# Auto-generated by the Agent Zero github plugin. Stateless auth:\n"
        "# read the token from A0 Secrets at call time; never stored by gh/git.\n"
        f'SECRETS_FILE="{secrets_file}"\n'
        f'SECRET_KEY="{key}"\n'
        'if [ -z "$GH_TOKEN" ] && [ -z "$GITHUB_TOKEN" ] && [ -f "$SECRETS_FILE" ]; then\n'
        '  tok=$(sed -n "s/^${SECRET_KEY}=//p" "$SECRETS_FILE" | head -n 1)\n'
        '  tok=${tok%\\"}; tok=${tok#\\"}; tok=${tok%\\\'}; tok=${tok#\\\'}\n'
        '  if [ -n "$tok" ]; then GH_TOKEN="$tok"; export GH_TOKEN; fi\n'
        "fi\n"
        f'exec "{bin_path}" "$@"\n'
    )
    try:
        with open(WRAPPER_PATH, "w") as f:
            f.write(script)
        os.chmod(
            WRAPPER_PATH,
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
        )
        return True
    except Exception as e:
        _log(f"could not write gh wrapper at {WRAPPER_PATH}: {e}")
        return False


def configure_git() -> bool:
    """Route git push/pull for github.com through the gh wrapper (scoped, reversible)."""
    try:
        subprocess.run(
            ["git", "config", "--global", "--replace-all",
             GIT_CREDENTIAL_KEY, GIT_CREDENTIAL_VALUE],
            capture_output=True, text=True, timeout=30,
        )
        return True
    except Exception as e:
        _log(f"could not configure git credential helper: {e}")
        return False


def unconfigure_git() -> None:
    """Remove only the github.com credential helper this plugin added."""
    try:
        subprocess.run(
            ["git", "config", "--global", "--unset-all",
             GIT_CREDENTIAL_KEY, GIT_CREDENTIAL_VALUE],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as e:
        _log(f"could not unset git credential helper: {e}")


def ensure() -> None:
    """Full boot/install routine: binary -> wrapper -> git config. Best-effort throughout."""
    if not ensure_binary():
        return
    ensure_wrapper()
    configure_git()
    cfg = _config()
    if not os.path.exists(_secrets_file()):
        _log(
            f"no Secrets file yet; add '{_secret_key(cfg)}' under "
            "Settings > External Services > Secrets to authenticate."
        )


def remove_wrapper() -> None:
    """Remove the shared-location wrapper. Called on uninstall (plugin dir is deleted separately)."""
    try:
        if os.path.islink(WRAPPER_PATH) or os.path.exists(WRAPPER_PATH):
            os.remove(WRAPPER_PATH)
            _log("removed gh wrapper.")
    except Exception as e:
        _log(f"could not remove gh wrapper: {e}")


def cleanup() -> None:
    """Full uninstall cleanup: remove the wrapper and the git credential helper."""
    remove_wrapper()
    unconfigure_git()
