from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.core.validators import validate_email

from data.user import user_name_exist, create_user_and_user_extend, get_user_by_name, get_user_by_id, user_mail_already_used


def public_lobby(request):
    return render(request, 'public_lobby.html')

