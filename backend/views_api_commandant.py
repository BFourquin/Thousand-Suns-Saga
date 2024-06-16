from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.validators import validate_email


from backend.utils import request_params
from data.user import user_name_exist, create_user_and_user_extend, get_user_by_name, get_user_by_object_id
from backend.api_ui_interactions import api_pop_up, api_pop_up_and_redirect
from data import server_details


def api_can_join_server(request):

    params = request_params(request)

    # Check server exist
    if not 'server_name' in params \
       or not any(s['server_name'] == params['server_name'] for s in server_details.get_all_servers_details()):
            #return pop_up({"title": "Aucun mot de passe spécifié", "level": "danger"}, status=400)
            return api_pop_up_and_redirect({"title": "Ce serveur n'existe pas", "level": "success"}, status=400, redirect='/servers_list/')

    # Check multiaccount



def api_create_commandant(request):

    params = request_params(request)

    # ##### USERNAME ######
    if not 'commandant_name' in params:
        return api_pop_up({"title": "Aucun nom de commandant spécifié", "level": "danger"}, status=400)

    if user_name_exist(params['commandant_name']):
        return api_pop_up({"title": "Ce nom de commandant est déjà pris", "level": "danger"}, status=400)

    if not 5 <= len(params['commandant_name']) <= 25:
        return api_pop_up({"title": "Votre nom de commandant doit faire entre 5 et 25 caractères", "level": "danger"}, status=400)


    # ##### CIVILISATION ######
    if not 'civilisation_name' in params:
        return api_pop_up({"title": "Aucun nom de civilisation spécifié", "level": "danger"}, status=400)

    if user_name_exist(params['civilisation_name']):
        return api_pop_up({"title": "Ce nom de civilisation est déjà pris", "level": "danger"}, status=400)

    if not 5 <= len(params['civilisation_name']) <= 40:
        return api_pop_up({"title": "Votre nom de civilisation doit faire entre 5 et 40 caractères", "level": "danger"}, status=400)


    #create_commandant()


    return api_pop_up_and_redirect({"title": "Compte créé", "level": "success"}, status=302, redirect='/user_account/')



def get_commandant(request):

    params = request_params(request)
    user = None

    if 'id' in params:
        user = get_user_by_object_id(params['id'])
    if 'username' in params:
        user = get_user_by_name(params['username'])

    if not user:
        return JsonResponse({"error": "Compte inexistant."}, status=400)

    user['_id'] = str(user['_id'])  # ObjectId is not serializable
    del user['password']  # Don't communicate the password hash...
    return JsonResponse({'user': user}, status=200)
