from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.core.validators import validate_email
from bokeh.plotting import figure
from bokeh.embed import components


from backend import utils
from data import server_details


def admin_login(request):

    params = utils.request_params(request)

    if utils.parameters_presents(('username', 'password'), params):

        username = params['username']
        password = params['password']
        user = authenticate(username=username, password=password)
        print(user)
        if user is not None and user.is_superuser and user.is_active:
            login(request, user)
            return redirect('admin_main_dashboard')

    return render(request, 'admin_login.html')


@staff_member_required
def bokeh_exemple(request):

    if not request.user.is_superuser:
        return render(request, 'admin_login.html')

    # create a plot
    plot = figure(plot_width=400, plot_height=400)

    # add a circle renderer with a size, color, and alpha
    plot.circle([1, 2, 3, 4, 5], [6, 7, 2, 4, 5], size=20, color="navy", alpha=0.5)
    bokeh_script, bokeh_div = components(plot)

    return render(request, 'bokeh_exemple.html', {'bokeh_script': bokeh_script, 'bokeh_div': bokeh_div})


@staff_member_required
def admin_main_dashboard(request):
    if not request.user.is_superuser:
        return render(request, 'admin_login.html')
    return render(request, 'admin_main_dashboard.html')

########################################################################################################################
# SERVERS STATES

@staff_member_required
def admin_servers_states(request):
    return render(request, 'admin_servers_states.html', {'servers_details': server_details.get_all_servers_details()})

@staff_member_required
def admin_servers_states_edit(request):
    params = utils.request_params(request)
    if params['value'] == 'true':
        params['value'] = True
    if params['value'] == 'false':
        params['value'] = False
    server_details.change_server_param(params['server_name'], params['type'], params['value'])
    return redirect(admin_servers_states)
