from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.validators import validate_email


from backend.utils import request_params
from data.user import user_name_exist, create_user_and_user_extend, get_user_by_name, get_user_by_object_id
from data import server_details


def can_join_server(request):

    print(server_details.get_all_servers_details())

    # Check server exist
    if not 'server_name' in params \
       or not any(s['server_name'] == params['server_name'] for s in server_details.get_all_servers_details()):
            return redirect('/servers_list/', {'title': "Ce serveur n'existe pas"})


    # Check multiaccount



def create_commandant(request):

    params = request_params(request)

    # ##### USERNAME ######
    if not 'username' in params:
        return JsonResponse({"message": "Aucun nom d'utilisateur spécifié."}, status=422)
    print(params['username'], user_name_exist(params['username']), get_user_by_name(params['username']))

    if user_name_exist(params['username']):
        return JsonResponse({"message": "Ce nom de commandant est déjà pris."}, status=422)

    if not 5 < len(params['username']) < 25:
        return JsonResponse({"message": "Votre pseudo doit faire entre 5 et 25 caractères."}, status=422)

    return JsonResponse({"message": "Compte créé."}, status=200)



def get_commandant(request):

    params = request_params(request)
    user = None

    if 'id' in params:
        user = get_user_by_object_id(params['id'])
    if 'username' in params:
        user = get_user_by_name(params['username'])

    if not user:
        return JsonResponse({"error": "Compte inexistant."}, status=422)

    user['_id'] = str(user['_id'])  # ObjectId is not serializable
    del user['password']  # Don't communicate the password hash...
    return JsonResponse({'user': user}, status=200)
