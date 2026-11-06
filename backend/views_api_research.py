from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from backend.api_ui_interactions import api_pop_up, api_pop_up_and_redirect, api_login_required
from backend.utils import request_params, get_active_server_and_commandant_from_request, get_request_user
from backend.views_api_buildings import no_active_commandant
from data.errors import GameError
from data.research import start_research


@require_POST
@api_login_required
def api_start_research(request):

    server, commandant = get_active_server_and_commandant_from_request(request)
    if not server or not commandant:
        return no_active_commandant()

    try:
        tech = start_research(server, commandant['id'], request_params(request).get('technology'), get_request_user(request)['language'])
    except GameError as error:
        return api_pop_up({"title": str(error), "level": "danger"}, status=400)

    return api_pop_up_and_redirect({"title": _("Recherche lancée"), "level": "success"}, status=200,
                                   redirect='/technologies/?category=' + str(tech.get('tech_type')))
