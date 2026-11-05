from django.views.decorators.http import require_POST


from backend.utils import request_params
from backend.api_ui_interactions import api_pop_up, api_pop_up_and_redirect, api_login_required
from data import server_details, commandant
from data.errors import GameError


def api_can_join_server(request):

    params = request_params(request)

    # Check server exist
    if not 'server_name' in params \
       or not any(s['server_name'] == params['server_name'] for s in server_details.get_all_servers_details()):
            #return pop_up({"title": "Aucun mot de passe spécifié", "level": "danger"}, status=400)
            return api_pop_up_and_redirect({"title": "Ce serveur n'existe pas", "level": "success"}, status=400, redirect='/servers_list/')

    # Check multiaccount
    #TODO





@require_POST
@api_login_required
def api_create_commandant(request):

    params = request_params(request)

    # ##### SERVER ######
    server = server_details.get_server_details(params.get('server'))
    if not server:
        return api_pop_up({"title": "Ce serveur n'existe pas", "level": "danger"}, status=400)

    if server['status'] != 'open' and not request.user.is_superuser:
        return api_pop_up({"title": "Ce serveur n'accepte pas de nouveaux joueurs", "level": "danger"}, status=400)


    # ##### USERNAME ######
    if not 'commandant_name' in params:
        return api_pop_up({"title": "Aucun nom de commandant spécifié", "level": "danger"}, status=400)

    if commandant.commandant_field_taken(server['server_name'], 'commandant_name', params['commandant_name']):
        return api_pop_up({"title": "Ce nom de commandant est déjà pris", "level": "danger"}, status=400)

    if not 5 <= len(params['commandant_name']) <= 25:
        return api_pop_up({"title": "Votre nom de commandant doit faire entre 5 et 25 caractères", "level": "danger"}, status=400)


    # ##### CIVILISATION ######
    if not 'civilisation_name' in params:
        return api_pop_up({"title": "Aucun nom de civilisation spécifié", "level": "danger"}, status=400)

    if commandant.commandant_field_taken(server['server_name'], 'civilisation_name', params['civilisation_name']):
        return api_pop_up({"title": "Ce nom de civilisation est déjà pris", "level": "danger"}, status=400)

    if not 5 <= len(params['civilisation_name']) <= 40:
        return api_pop_up({"title": "Votre nom de civilisation doit faire entre 5 et 40 caractères", "level": "danger"}, status=400)


    try:
        commandant.create_commandant(server['server_name'], request.user.username,
                                     params['commandant_name'],
                                     params['civilisation_name'])
    except GameError as e:
        return api_pop_up({"title": str(e), "level": "danger"}, status=400)

    return api_pop_up_and_redirect({"title": "Compte créé", "level": "success"}, status=200, redirect='/user_account/')

