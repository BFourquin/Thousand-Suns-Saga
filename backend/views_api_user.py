from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.validators import validate_email

from backend.api_ui_interactions import pop_up, pop_up_and_redirect
from data.user import user_name_exist, create_user_and_user_extend, get_user_by_name, get_user_by_object_id, user_mail_already_used


def request_params(request):
    # return parameters passed by both GET and POST methods
    params = request.POST.copy()
    params.update(request.GET)
    return params


def create_user(request):

    params = request_params(request)

    # ##### USERNAME ######
    if not 'username' in params:
        return pop_up({"title": "Aucun nom d'utilisateur spécifié", "level": "danger"}, status=400)
    print(params['username'], user_name_exist(params['username']), get_user_by_name(params['username']))
    if user_name_exist(params['username']):
        return pop_up({"title": "Ce nom de compte est déjà pris", "level": "danger"}, status=400)
    if not 5 < len(params['username']) < 25:
        return pop_up({"title": "Votre pseudo doit faire entre 5 et 25 caractères", "level": "danger"}, status=400)

    # ##### EMAIL ######
    if not 'email' in params:
        return pop_up({"title": "Aucun email spécifié", "level": "danger"}, status=400)
    try:
        validate_email(params['email'])  # Only check if it's an email format, not if it really exist
    except:
        return pop_up({"title": "Adresse email non valide", "level": "danger"}, status=400)
    if user_mail_already_used(params['email']):
        return pop_up({"title": "Un compte est déjà lié à cette adresse mail", "level": "danger"}, status=400)

    # ##### PASSWORD ######
    if not 'password' in params:
        return pop_up({"title": "Aucun mot de passe spécifié", "level": "danger"}, status=400)

    user = create_user_and_user_extend(params['username'], params['email'], params['password'])
    return pop_up_and_redirect({"title": "Compte créé", "level": "success"}, status=302, redirect='/player_login/')


def get_user(request):

    params = request_params(request)
    user = None

    if 'id' in params:
        user = get_user_by_object_id(params['id'])
    if 'username' in params:
        user = get_user_by_name(params['username'])

    if not user:
        return pop_up({"title": "Compte inexistant", "level": "danger"}, status=400)

    user['_id'] = str(user['_id'])  # ObjectId is not serializable
    del user['password']  # Don't communicate the password hash...
    return JsonResponse({'user': user}, status=200)
