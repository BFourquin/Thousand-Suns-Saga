import datetime

from django.shortcuts import render, redirect
from django.contrib.auth import login


from backend.login import throttled_authenticate
from data import server_details
from data import cycles



def public_homepage(request):
    return render(request, 'public/public_homepage.html')



def servers_list(request):

    # A player looking for a server must not read an old menu saying it isn't open yet
    server_details.refresh_servers_menu()

    servers = server_details.get_all_servers_details()
    for i in range(len(servers)):
        servers[i]['cycles'] = cycles.get_current_cycle(servers[i]['server_name'])
        servers[i]['open_since_days'] = (datetime.datetime.now() - servers[i]['opening_date']).days

    servers = sorted(servers, key=lambda d: d['opening_date'], reverse=True)


    return render(request, 'public/servers_list.html', {'servers_details': servers})




########################################################################################################################
# LOGIN / INSCRIPTION / RESET PASSWORD /  ...


def player_login(request):

    login_error = None

    if request.method == 'POST':
        user, login_error = throttled_authenticate(request)
        if user is not None:
            login(request, user)
            return redirect('/user_account/')

    return render(request, 'public/player_login.html', {'login_error': login_error})



def player_register(request):
    # The form is sent to the JSON API create_user by includes/form_submit_to_json_api.js
    return render(request, 'public/player_register.html')
