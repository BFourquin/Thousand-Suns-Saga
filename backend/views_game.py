from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.core.validators import validate_email
from bokeh.plotting import figure
from bokeh.embed import components
import time

import data.user
from backend.utils import request_params, parameters_presents
from data import server_details, user, technology, sectors, systems, coordinates, map_generator
from data.user import get_user_by_name, get_user_by_object_id, update_user


@login_required
def user_account(request):

    user = get_user_by_name(str(request.user))
    params = request_params(request)

    if 'language' in params and params['language'] in ('fr', 'en'):
        data.user.update_user(user, 'language', params['language'])
        time.sleep(0.5)  # DB delay ?
    if 'dark_mode' in params and params['language'] in ('true', 'false'):
        darkmode = params['language'] == 'true'
        data.user.update_user(user, 'dark_mode', darkmode)
        time.sleep(0.5)  # DB delay ?

    return render(request, 'game/user_account.html', {'user': dict(user)})
