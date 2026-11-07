
from data import server_details
from data.conversations import count_unread_conversations
from data.ententes import count_pending_answers
from data.forums import count_all_open_flags, get_forum_badges
from data.themes import get_theme_or_default, LIGHT_THEMES
from database.schemas import server_schema
from backend.utils import get_active_server_and_commandant_from_request, get_request_user, orders_closed


def servers_details(request):
    return server_details.get_servers_menu()



def user_account(request):

    user_account = get_request_user(request)
    theme = get_theme_or_default(user_account.get('theme') if user_account else None)

    # Only the classic theme lets the player choose between dark and light
    dark_mode = (user_account['dark_mode'] if user_account else True) if theme == 'classic' else theme not in LIGHT_THEMES

    context = {'dark_mode': dark_mode, 'theme': theme}
    if user_account:
        context['user_account'] = user_account
    return context



def commandant_and_server(request):

    server, commandant = get_active_server_and_commandant_from_request(request)
    details = server_details.get_server_details(server) if server else None

    nb_unread_conversations, forum_badges, nb_entente_answers = 0, {}, 0
    if commandant:
        with server_schema(server):  # Rendered outside the schema of the view : once for the three counters
            nb_unread_conversations = count_unread_conversations(server, commandant['id'])
            forum_badges = get_forum_badges(server, commandant['id'])
            nb_entente_answers = count_pending_answers(server, commandant['id'])

    if details and details['roleplay'] == 'RP':  # Its HRP forum is closed : nothing there can be read
        forum_badges.pop('hrp', None)

    return {'server': server,
            'commandant': commandant,
            'read_only': orders_closed(request),
            'server_details': details,
            'nb_unread_conversations': nb_unread_conversations,
            'forum_badges': forum_badges,
            'nb_communication': nb_unread_conversations + sum(forum_badges.values()),
            'nb_entente_answers': nb_entente_answers,
            'nb_open_flags': count_all_open_flags() if request.user.is_superuser else 0}
