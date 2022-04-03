from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.validators import validate_email


from utils import request_params
from data.user import user_name_exist, create_user_and_user_extend, get_user_by_name, get_user_by_object_id, user_mail_already_used


def create_commandant(request):

    params = request_params(request)

    # ##### USERNAME ######
    if not 'username' in params:
        return JsonResponse({"message": "Aucun nom d'utilisateur spécifié."}, status=422)
    print(params['username'], user_name_exist(params['username']), get_user_by_name(params['username']))
    if user_name_exist(params['username']):
        return JsonResponse({"message": "Ce nom de compte est déjà pris."}, status=422)
    if not 5 < len(params['username']) < 25:
        return JsonResponse({"message": "Votre pseudo doit faire entre 5 et 25 caractères."}, status=422)

    # ##### EMAIL ######
    if not 'email' in params:
        return JsonResponse({"message": "Aucun email spécifié."}, status=422)
    try:
        validate_email(params['email'])  # Only check if it's an email format, not if it really exist
    except:
        return JsonResponse({"message": "Adresse email non valide."}, status=422)
    if user_mail_already_used(params['email']):
        return JsonResponse({"message": "Un compte est déjà lié à cette adresse mail."}, status=422)

    # ##### PASSWORD ######
    if not 'password' in params:
        return JsonResponse({"message": "Aucun mot de passe spécifié."}, status=422)

    user = create_user_and_user_extend(params['username'], params['email'], params['password'])
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
