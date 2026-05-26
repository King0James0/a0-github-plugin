from helpers.extension import Extension
from usr.plugins.github.helpers import gh_setup


class GithubGhSetup(Extension):
    """Ensure the gh CLI is installed, wrapped, and authenticated on every boot."""

    def execute(self, **kwargs):
        gh_setup.ensure()
