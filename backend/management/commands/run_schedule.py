from django.core.management.base import BaseCommand

from anticheat.rules import purge_old_logs, scan_due_servers
from data.schedule import run_due_steps


class Command(BaseCommand):
    help = "To run every 5 minutes : plays the steps of the game whose hour has come, then the anticheat (see data/schedule.py)"

    def handle(self, *args, **options):
        played = run_due_steps()  # First : the steps of the game are expected at their hour
        purge_old_logs()
        scanned = scan_due_servers()
        self.stdout.write('Played : ' + (', '.join(played) or 'nothing due') + '\nAnticheat : ' + (', '.join(scanned) or 'nothing due'))
