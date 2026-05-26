"""Framework runtime hooks for the GitHub plugin.

Runs in the Agent Zero framework runtime (/opt/venv-a0), called by the plugin
installer/uninstaller via helpers.plugins.call_plugin_hook.
"""


def install():
    """Set up gh immediately after the plugin is placed, without waiting for a restart."""
    from usr.plugins.github.helpers import gh_setup

    gh_setup.ensure()


def uninstall():
    """Remove the gh wrapper and the git credential helper this plugin added.

    The plugin dir (binary, config) is deleted separately by the framework.
    """
    from usr.plugins.github.helpers import gh_setup

    gh_setup.cleanup()
