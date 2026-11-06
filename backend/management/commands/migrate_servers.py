from django.core.management.base import BaseCommand

from backend.models import Server
from database.schemas import migrate_server


class Command(BaseCommand):
    help = "Apply the migrations of the app 'game' to the schema of every game server"

    def handle(self, *args, **options):
        for server in Server.objects.values_list('server_name', flat=True):
            migrate_server(server)
            self.stdout.write(server + ' : OK')
