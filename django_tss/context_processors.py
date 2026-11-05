
from data import server_details
from data.themes import get_theme_or_default
from backend.utils import get_active_server_and_commandant_from_request, get_request_user


def servers_details(request):
    return server_details.get_servers_menu()



def user_account(request):

    user_account = get_request_user(request)
    theme = get_theme_or_default(user_account.get('theme') if user_account else None)

    # Every theme but the classic one is a dark theme
    dark_mode = (user_account['dark_mode'] if user_account else True) if theme == 'classic' else True

    context = {'dark_mode': dark_mode, 'theme': theme}
    if user_account:
        context['user_account'] = user_account
    return context



def commandant_and_server(request):

    server, commandant = get_active_server_and_commandant_from_request(request)
    return {'server': server,
            'commandant': commandant,
            'server_details': server_details.get_server_details(server) if server else None}
