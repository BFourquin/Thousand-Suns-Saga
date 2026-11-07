from django.core.management.base import BaseCommand

from anticheat.rules import purge_old_logs, scan_due_servers


class Command(BaseCommand):
    help = "To run every hour : scans the servers whose hour_anticheat_checks has come, and purges the old journal"

    def handle(self, *args, **options):
        purge_old_logs()
        scanned = scan_due_servers()
        self.stdout.write('Scanned : ' + (', '.join(scanned) or 'nothing due at this hour'))
