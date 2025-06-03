import datetime

from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login


from backend.utils import request_params, parameters_presents
from data import server_details
from data import cycles



def public_homepage(request):
    return render(request, 'public/public_homepage.html')



def servers_list(request):

    servers = server_details.get_all_servers_details()
    for i in range(len(servers)):
        servers[i]['cycles'] = cycles.get_current_cycle(servers[i]['server_name'])
        servers[i]['open_since_days'] = (datetime.datetime.now() - servers[i]['opening_date']).days

    servers = sorted(servers, key=lambda d: d['opening_date'], reverse=True)


    return render(request, 'public/servers_list.html', {'servers_details': servers})




########################################################################################################################
# LOGIN / INSCRIPTION / RESET PASSWORD /  ...


def player_login(request):

    params = request_params(request)

    if parameters_presents(('username', 'password'), params):

        username = params['username']
        password = params['password']
        user = authenticate(username=username, password=password)
        if user is not None and user.is_active:
            login(request, user)
            return redirect('/user_account/')

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

