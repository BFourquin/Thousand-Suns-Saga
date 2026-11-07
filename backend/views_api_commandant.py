from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST


from backend.utils import clean_name, request_params
from backend.api_ui_interactions import api_pop_up, api_pop_up_and_redirect, api_login_required
from data import server_details, commandant
from data.errors import GameError


    # Check multiaccount
    #TODO





@require_POST
@api_login_required
def api_create_commandant(request):

    params = request_params(request)

    # ##### SERVER ######
    server = server_details.get_server_details(params.get('server'))
    if not server:
        return api_pop_up({"title": _("Ce serveur n'existe pas"), "level": "danger"}, status=400)

    if server['status'] != 'open' and not request.user.is_superuser:
        return api_pop_up({"title": _("Ce serveur n'accepte pas de nouveaux joueurs"), "level": "danger"}, status=400)


    # ##### USERNAME ######
    commandant_name = clean_name(params, 'commandant_name')
    if not commandant_name:
        return api_pop_up({"title": _("Aucun nom de commandant spécifié"), "level": "danger"}, status=400)

    if commandant.commandant_name_taken(commandant_name):
        return api_pop_up({"title": _("Ce nom de commandant est déjà pris"), "level": "danger"}, status=400)

    if not 5 <= len(commandant_name) <= 25:
        return api_pop_up({"title": _("Votre nom de commandant doit faire entre 5 et 25 caractères"), "level": "danger"}, status=400)


    # ##### CIVILISATION ######
    civilisation_name = clean_name(params, 'civilisation_name')
    if not civilisation_name:
        return api_pop_up({"title": _("Aucun nom de civilisation spécifié"), "level": "danger"}, status=400)

    if commandant.civilisation_name_taken(server['server_name'], civilisation_name):
        return api_pop_up({"title": _("Ce nom de civilisation est déjà pris"), "level": "danger"}, status=400)

    if not 5 <= len(civilisation_name) <= 40:
        return api_pop_up({"title": _("Votre nom de civilisation doit faire entre 5 et 40 caractères"), "level": "danger"}, status=400)


    try:
        commandant.create_commandant(server['server_name'], request.user.username, commandant_name, civilisation_name)
    except GameError as e:
        return api_pop_up({"title": str(e), "level": "danger"}, status=400)

    return api_pop_up_and_redirect({"title": _("Compte créé"), "level": "success"}, status=200, redirect='/user_account/')

