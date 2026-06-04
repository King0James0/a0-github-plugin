"""Framework runtime hooks for the GitHub plugin.

Runs in the Agent Zero framework runtime (/opt/venv-a0), called by the plugin
installer/uninstaller via helpers.plugins.call_plugin_hook.
"""


def install():
    """Set up gh immediately after the plugin is placed, without waiting for a restart."""
    from usr.plugins.github.helpers import gh_setup, watch_schedule

    gh_setup.ensure()
    watch_schedule.ensure()


def uninstall():
    """Remove the gh wrapper, the git credential helper, and the scheduled watch task.

    The plugin dir (binary, config) is deleted separately by the framework.
    """
    from usr.plugins.github.helpers import gh_setup, watch_schedule

    watch_schedule.remove()
    gh_setup.cleanup()


def save_plugin_config(settings=None, default=None, **kwargs):
    """Apply watch config the moment it is saved in the UI (no restart needed).

    Called by save_plugin_config BEFORE the new config is written to disk, so we
    reconcile straight from the incoming settings. Must return the settings so the
    framework persists them.
    """
    cfg = settings if isinstance(settings, dict) else default
    try:
        from usr.plugins.github.helpers import watch_schedule

        if isinstance(cfg, dict):
            watch_schedule.ensure_from(cfg)
    except Exception:
        pass
    return cfg
