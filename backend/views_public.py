from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.core.validators import validate_email
from bokeh.plotting import figure
from bokeh.embed import components


from backend.utils import request_params, parameters_presents
from data import server_details, user, technology, sectors, systems, coordinates, map_generator



def public_lobby(request):
    return render(request, 'public/public_lobby.html')



def player_login(request):

    params = request_params(request)

    if parameters_presents(('username', 'password'), params):

        username = params['username']
        password = params['password']
        user = authenticate(username=username, password=password)
        if user is not None and user.is_active:
            login(request, user)
            return redirect('user_account/')

    return render(request, 'public/player_login.html')



def player_register(request):

    params = request_params(request)

    if parameters_presents(('username', 'password'), params):

        email = params['email']
        username = params['username']
        password = params['password']

        # TODO Verification by email

        user = authenticate(username=username, password=password)

        if user is not None and user.is_active:
            login(request, user)
            return redirect('player_register')

    return render(request, 'public/player_register.html')

