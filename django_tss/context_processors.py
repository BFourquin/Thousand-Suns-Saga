
from django.utils import translation

from data import server_details
from data.user import get_user_by_name





def servers_details(request):

    game_servers = server_details.get_servers_names(open_servers=True, playable_servers=True, test_servers=False, old_servers=False, admin_visibility=True)
    test_servers = server_details.get_servers_names(open_servers=False, playable_servers=False, test_servers=True, old_servers=False, admin_visibility=True)
    old_servers = server_details.get_servers_names(open_servers=False, playable_servers=False, test_servers=False, old_servers=True, admin_visibility=True)

    return {'game_servers': game_servers, 'test_servers': test_servers, 'old_servers': old_servers}



def user_account(request):

    user_account = get_user_by_name(str(request.user))

    return {'user_account': user_account} if user_account else {}


def localization(request):

    if request.user:
        user_account = get_user_by_name(str(request.user))
        print(dict(request.session))
        if user_account and 'language' in user_account:
            translation.activate(user_account['language'])
    return {}
