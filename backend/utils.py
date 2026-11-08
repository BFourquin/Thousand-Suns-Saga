
from backend.models import FINISHED_SERVER_STATUSES, Server, to_id
from data.user import get_user_by_name


########################################################################################################################
# VIEWS FUNCTIONS

def request_params(request):
    # Return parameters passed by both GET and POST methods
    # Adapt request lists parameters into python list

    params = {}

    for key in request.POST:
        values = request.POST.getlist(key)
        if len(values) > 1:
            params[key] = values
        else:
            params[key] = values[0]

    for key in request.GET:
        values = request.GET.getlist(key)
        if len(values) > 1:
            params[key] = values
        else:
            params[key] = values[0]

    return params


def parameters_presents(params, request_params):
    # Verify if each wanted params are present in request

    # Single str as parameter
    if isinstance(params, str):
        return bool(params in request_params)

    # List of parameters
    for param in params:
        if not param in request_params:
            return False
    return True


def clean_name(params, key):
    # Spaces around a name would make it impossible to find, and PostgreSQL refuses the null character. A repeated parameter is a list.
    name = params.get(key, '')
    return name.replace('\x00', '').strip() if isinstance(name, str) else ''


def get_request_user(request):
    # Loaded once per request : views, decorators and context processors all need it

    if not hasattr(request, 'tss_user'):
        request.tss_user = get_user_by_name(request.user.username) if request.user.is_authenticated else None
    return request.tss_user


def get_active_server_and_commandant_from_request(request):
    from data.commandant import get_commandant

    if not hasattr(request, 'tss_active_commandant'):
        user = get_request_user(request)
        server = user['playing_on_server'] if user else None
        commandant_id = user['playing_on_commandant'] if user else None
        commandant = get_commandant(server, commandant_id) if server and commandant_id else None
        request.tss_active_commandant = (server, commandant)

    return request.tss_active_commandant


def orders_closed(request):
    # A finished server or a dead commandant : the player can still look at what was, but no order is accepted anymore

    if not hasattr(request, 'tss_orders_closed'):
        server, commandant = get_active_server_and_commandant_from_request(request)
        request.tss_orders_closed = bool(commandant) and (
            commandant['status'] != 'active' or Server.objects.filter(pk=server, status__in=FINISHED_SERVER_STATUSES).exists())
    return request.tss_orders_closed


def get_language(request):
    return get_request_user(request)['language']


def commandant_owns_colony(commandant, colony_id):
    return to_id(colony_id) in commandant['colonies']


def info_from_seed(seed):
    """Get back infos from a seed"""
    seed = str(seed)
    infos = {}
    if len(seed) >= 4:
        infos['server_seed'] = seed[0:4]
    if len(seed) >= 10:
        infos['sector_id'] = seed[0:10]
    if len(seed) >= 16:
        infos['system_id'] = seed[0:16]

    if len(seed) >= 13:
        infos['pos_y'] = seed[10:13]
    if len(seed) >= 16:
        infos['pos_x'] = seed[13:16]

    if len(seed) >= 18:
        infos['pos_orbital'] = seed[16:18]
    return infos
