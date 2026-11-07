from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from dateutil import tz

from backend.models import CommandantAccount, Server, UserExtended
from database.schemas import create_server_schema, drop_server_schema, on_server
from game.models import Commandant


SERVERS_MENU_CACHE_KEY = 'servers_menu'
SERVERS_MENU_CACHE_SECONDS = 5 * 60


# SERVER STATUS :
server_status = ('open',  # users can create an account and play
                 'close',  # users can play but not create new accounts
                 'test',  # only superuser can create an account
                 'stop',  # the server is fixed in time at the end of the game, no new account or any order,
                 'dead')  # everything shut down


@transaction.atomic
def create_server(server_name, version, status='test', admin_only_visibility=True,
                  language='fr', roleplay='HRP', gameplay='saga', timezone_name='Europe/Paris', exclusive=False):

    if Server.objects.filter(pk=server_name).exists():
        raise Exception("'" + server_name + "' already exist.")
    if status not in server_status:
        raise Exception("'" + status + "' is not valid as a server state.")

    server = Server.objects.create(server_name=server_name,
                                   version=version,
                                   gameplay=gameplay,
                                   status=status,
                                   admin_only_visibility=admin_only_visibility,
                                   creation_date=timezone.now(),
                                   opening_date=timezone.now(),
                                   language=language,
                                   roleplay=roleplay,
                                   exclusive=exclusive,
                                   timezone=timezone_name)
    create_server_schema(server_name)
    return server


def get_servers_names(open_servers=True, playable_servers=True, test_servers=True, old_servers=True, admin_visibility=False):
    servers_list = []
    for server in Server.objects.values('server_name', 'status', 'admin_only_visibility'):

        if server['admin_only_visibility'] and not admin_visibility:
            continue

        status = server['status']
        if (open_servers and status == 'open' ) or \
           (playable_servers and status in ('open', 'close') ) or \
           (test_servers and status == 'test' ) or \
           (old_servers and status in ('stop', 'dead') ):
                servers_list.append(server['server_name'])

    return servers_list


def get_servers_menu():
    # Displayed by the menu of every page, so kept in cache instead of being read at each request
    # shortcut: the default cache is per process, each worker refreshes on its own within SERVERS_MENU_CACHE_SECONDS
    return cache.get_or_set(SERVERS_MENU_CACHE_KEY, lambda: {
        'game_servers': get_servers_names(open_servers=True, playable_servers=True, test_servers=False, old_servers=False, admin_visibility=True),
        'test_servers': get_servers_names(open_servers=False, playable_servers=False, test_servers=True, old_servers=False, admin_visibility=True),
        'old_servers': get_servers_names(open_servers=False, playable_servers=False, test_servers=False, old_servers=True, admin_visibility=True),
    }, SERVERS_MENU_CACHE_SECONDS)


def refresh_servers_menu():
    cache.delete(SERVERS_MENU_CACHE_KEY)


def get_server_details(server_name):
    server = Server.objects.filter(pk=server_name).first()
    return server.as_dict() if server else None


def get_all_servers_details():
    return [server.as_dict() for server in Server.objects.all()]


def get_tz(server_name):
    return tz.gettz(Server.objects.values_list('timezone', flat=True).get(pk=server_name))


def change_server_param(server_name, param, param_value):
    Server.objects.filter(pk=server_name).update(**{param: param_value})


@transaction.atomic
def delete_server_details(server_name):
    # To be used only on test servers ! Everything belonging to the server goes with it
    UserExtended.objects.filter(playing_on_server=server_name).update(playing_on_commandant=None)
    drop_server_schema(server_name)
    return Server.objects.filter(pk=server_name).delete()


########################################################################################################################
# Commandants lists

@on_server
@transaction.atomic
def set_dead_commandant(server_name, commandant_id):
    Commandant.objects.filter(id=commandant_id).update(status='dead')
    CommandantAccount.objects.filter(server=server_name, commandant_id=commandant_id).update(status='dead')
