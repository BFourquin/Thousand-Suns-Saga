from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.views.decorators.http import require_POST

from backend.api_ui_interactions import api_pop_up, api_pop_up_and_redirect
from data.user import user_name_exist, create_user_and_user_extend, user_mail_already_used


def request_params(request):
    # return parameters passed by both GET and POST methods
    params = request.POST.copy()
    params.update(request.GET)
    return params


@require_POST
def create_user(request):

    params = request_params(request)

    # ##### USERNAME ######
    if not 'username' in params:
        return api_pop_up({"title": "Aucun nom d'utilisateur spécifié", "level": "danger"}, status=400)
    if user_name_exist(params['username']):
        return api_pop_up({"title": "Ce nom de compte est déjà pris", "level": "danger"}, status=400)
    if not 5 < len(params['username']) < 25:
        return api_pop_up({"title": "Votre pseudo doit faire entre 5 et 25 caractères", "level": "danger"}, status=400)

    # ##### EMAIL ######
    if not 'email' in params:
        return api_pop_up({"title": "Aucun email spécifié", "level": "danger"}, status=400)
    try:
        validate_email(params['email'])  # Only check if it's an email format, not if it really exist
    except:
        return api_pop_up({"title": "Adresse email non valide", "level": "danger"}, status=400)
    if user_mail_already_used(params['email']):
        return api_pop_up({"title": "Un compte est déjà lié à cette adresse mail", "level": "danger"}, status=400)

    # ##### PASSWORD ######
    if not 'password' in params:
        return api_pop_up({"title": "Aucun mot de passe spécifié", "level": "danger"}, status=400)

    try:
        validate_password(params['password'], user=User(username=params['username'], email=params['email']))
    except ValidationError as e:
        return api_pop_up({"title": "Mot de passe trop faible", "body": ' '.join(e.messages), "level": "danger"}, status=400)

    user = create_user_and_user_extend(params['username'], params['email'], params['password'])
    return api_pop_up_and_redirect({"title": "Compte créé", "level": "success"}, status=200, redirect='/player_login/')
