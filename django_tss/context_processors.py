
from django.utils import translation

from data import server_details
from data.user import get_user_by_name
from data.cycles import get_current_cycle
from backend.utils import get_active_server_and_commandant_from_request


def servers_details(request):

    game_servers = server_details.get_servers_names(open_servers=True, playable_servers=True, test_servers=False, old_servers=False, admin_visibility=True)
    test_servers = server_details.get_servers_names(open_servers=False, playable_servers=False, test_servers=True, old_servers=False, admin_visibility=True)
    old_servers = server_details.get_servers_names(open_servers=False, playable_servers=False, test_servers=False, old_servers=True, admin_visibility=True)

    return {'game_servers': game_servers, 'test_servers': test_servers, 'old_servers': old_servers}



def user_account(request):

    user_account = get_user_by_name(str(request.user))
    dark_mode = user_account['dark_mode'] if user_account else True
    return {'user_account': user_account,
            'dark_mode': dark_mode} if user_account else {'dark_mode': dark_mode}



def commandant_and_server(request):

    server, commandant = get_active_server_and_commandant_from_request(request)
    return {'server': server,
            'commandant': commandant,
            'server_details': server_details.get_server_details(server)}



def localization(request):

    if request.user:
        user_account = get_user_by_name(str(request.user))
        if user_account and 'language' in user_account:
            translation.activate(user_account['language'])
    return {}


def cycle_info(request):

    if request.user:
        user_account = get_user_by_name(str(request.user))
        if not user_account:
            return {}

        cycle = get_current_cycle(user_account['playing_on_server'])
        return {'cycle_info': cycle}
    return {}
