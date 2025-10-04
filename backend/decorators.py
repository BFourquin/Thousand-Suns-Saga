
from functools import wraps
from bson.objectid import ObjectId
from django.utils import timezone

from data.user import get_user_by_name
from data.cycles import get_current_cycle
from data.commandant import get_commandant_by_object_id, update_commandant
from backend.utils import get_active_server_and_commandant_from_request


def log_player_action(view_func):
    """
    Décorateur pour enregistrer le moment où un joueur déclenche une action.
    - Met à jour le champ time_cycle_finished dans MongoDB
    - Prépare la collecte des infos pour un log complet (TODO)
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        user = getattr(request, "user", None)
        now = timezone.now()

        if user and user.is_authenticated:
            server, commandant = get_active_server_and_commandant_from_request(request)

            if server and commandant:
                update_commandant(server, commandant['_id'], "time_last_activity", now)

        # --- TODO ---
        # Enregistrer dans MongoDB ou autre :
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
            user_account = get_user_by_name(str(request.user))
            if user_account and user_account.get("playing_on_server"):
                server_name = user_account["playing_on_server"]
                cycle = get_current_cycle(server_name)

                commandants_cycle_playing = []
                commandants_cycle_finished = []

                for commandant_id in cycle['commandants_cycle_playing']:
                    commandants_cycle_playing.append(get_commandant_by_object_id(server_name, commandant_id))
                for commandant_id in cycle['commandants_cycle_finished']:
                    commandants_cycle_finished.append(get_commandant_by_object_id(server_name, commandant_id))
                ratio_finished = len(commandants_cycle_finished) / (len(commandants_cycle_finished)+len(commandants_cycle_playing)) if commandants_cycle_finished else 0


                current_commandant_id = ObjectId(user_account['playing_on_commandant'])
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
