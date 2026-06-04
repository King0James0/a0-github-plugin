from helpers.extension import Extension
from usr.plugins.github.helpers import watch_schedule


class GithubWatchSchedule(Extension):
    """Reconcile the hourly github-watch scheduled task with plugin config on boot."""

    def execute(self, **kwargs):
        watch_schedule.ensure()
