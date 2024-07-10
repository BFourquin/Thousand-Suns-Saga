from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.core.validators import validate_email
from bokeh.plotting import figure
from bokeh.embed import components
import datetime

import data.user
from backend.utils import request_params, parameters_presents
from data import server_details, user, technology, sectors, systems, coordinates, map_generator
from data.user import get_user_by_name, get_user_by_object_id, update_user


@login_required(login_url='/player_login/')
def user_account(request):

    user = get_user_by_name(str(request.user))
    params = request_params(request)

    if 'language' in params and params['language'] in ('fr', 'en'):
        data.user.update_user(user, 'language', params['language'])


    if 'dark_mode' in params and params['dark_mode'] in ('true', 'false'):
        darkmode = params['dark_mode'] == 'true'
        data.user.update_user(user, 'dark_mode', darkmode)

    user = get_user_by_name(str(request.user))  # Get it again in case of parameter changed

    return render(request, 'game/user_account.html', {'current_user': dict(user)})



@login_required(login_url='/player_login/')
def create_commandant(request):

    params = request_params(request)

    if not 'server_name' in params:
        redirect('servers_list')

    server = server_details.get_server_details(params['server_name'])

    if not server :
        redirect('servers_list')

    server['open_since_days'] = (datetime.datetime.now() - server['opening_date']).days

    return render(request, 'game/create_commandant.html', {'server': server})
