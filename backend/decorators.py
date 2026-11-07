
from functools import wraps
from django.shortcuts import redirect
from django.utils import timezone

from data.cycles import get_current_cycle
from data.commandant import get_commandants, update_commandant
from backend.utils import get_active_server_and_commandant_from_request, get_request_user, orders_closed
from database.schemas import server_schema


def log_player_action(view_func):
    """
    Décorateur pour enregistrer le moment où un joueur déclenche une action.
    - Met à jour le champ time_last_activity du commandant
    - Prépare la collecte des infos pour un log complet (TODO)
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = getattr(request, "user", None)
        now = timezone.now()

        if user and user.is_authenticated:
            server, commandant = get_active_server_and_commandant_from_request(request)

            if server and commandant and not orders_closed(request):  # Looking at an old game is no activity in it
                update_commandant(server, commandant['id'], "time_last_activity", now)

        # --- TODO ---
        # Enregistrer en base ou autre :
        # - user_id
        # - méthode HTTP
        # - path
        # - GET / POST data
        # - datetime
        # Exemple :
        # log_action({
        #     "user": user.username,
        #     "method": request.method,
        #     "path": request.path,
        #     "params": request.GET.dict(),
        #     "data": request.POST.dict(),
        #     "timestamp": now,
        # })

        return view_func(request, *args, **kwargs)
    return wrapper



def add_cycle_info(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        response = view_func(request, *args, **kwargs)

        context_dict = {}
        if getattr(request, "user", None):
            user_account = get_request_user(request)
            if user_account and user_account.get("playing_on_server"):
                server_name = user_account["playing_on_server"]
                with server_schema(server_name):
                    cycle = get_current_cycle(server_name)
                    commandants = {commandant['id']: commandant for commandant in get_commandants(
                        server_name, cycle['commandants_cycle_playing'] + cycle['commandants_cycle_finished'])}

                commandants_cycle_playing = [commandants[_id] for _id in cycle['commandants_cycle_playing'] if _id in commandants]
                commandants_cycle_finished = [commandants[_id] for _id in cycle['commandants_cycle_finished'] if _id in commandants]
                ratio_finished = len(commandants_cycle_finished) / (len(commandants_cycle_finished)+len(commandants_cycle_playing)) if commandants_cycle_finished else 0


                current_commandant_id = user_account['playing_on_commandant']
                current_commandant_finished = current_commandant_id in cycle['commandants_cycle_finished']
                current_commandant_absent = current_commandant_id in cycle['commandants_cycle_absent']


                context_dict = {
                    "cycle_info": cycle,
                    "commandants_cycle_playing": commandants_cycle_playing,
                    "commandants_cycle_finished": commandants_cycle_finished,
                    "ratio_finished": ratio_finished,
                    "current_commandant_finished": current_commandant_finished,
                    "current_commandant_absent": current_commandant_absent,
                }


        if hasattr(response, "context_data"):  # cas TemplateResponse
            response.context_data.update(context_dict)
        elif hasattr(response, "context"):    # cas rendu via render()
            response.context.update(context_dict)

        return response
    return _wrapped_view



def commandant_required(view_func):
    # Give the active server and commandant to the view, send the player to the account page without them

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        server, commandant = get_active_server_and_commandant_from_request(request)
        if not server or not commandant:
            return redirect('/user_account/')
        if request.method == 'POST' and orders_closed(request):  # Back to the page, which explains why
            return redirect(request.get_full_path())
        with server_schema(server):  # Once for the whole view instead of at each call to the data layer
            return view_func(request, server, commandant, *args, **kwargs)
    return wrapper
