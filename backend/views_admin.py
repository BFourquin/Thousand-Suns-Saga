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
from data import server_details, user, technology, sectors, systems, coordinates


def admin_login(request):

    params = request_params(request)

    if parameters_presents(('username', 'password'), params):

        username = params['username']
        password = params['password']
        user = authenticate(username=username, password=password)
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
# GENERAL ADMINISTRATION PAGES
########################################################################################################################

# ACCOUNTS
@staff_member_required
def admin_user_accounts(request):
    return render(request, 'admin_user_accounts.html', {'user_accounts': user.get_all_users(strify=True)})


@staff_member_required
def admin_user_details(request):
    id = request_params(request)['id']
    user_account = user.get_user_by_id(id)
    user_account['objectid'] = user_account['_id']
    return render(request, 'admin_user_details.html', {'user': user_account})


# ##########################################################
# SERVERS STATES

@staff_member_required
def admin_servers_states(request):
    return render(request, 'admin_servers_states.html', {'servers_details': server_details.get_all_servers_details()})


@staff_member_required
def admin_servers_states_edit(request):
    params = request_params(request)
    if params['value'] == 'true':
        params['value'] = True
    if params['value'] == 'false':
        params['value'] = False
    server_details.change_server_param(params['server_name'], params['type'], params['value'])
    return redirect(admin_servers_states)


########################################################################################################################
# SERVER SPECIFIC ADMINISTRATION
########################################################################################################################


@staff_member_required
def admin_technology(request):
    params = request_params(request)
    if not 'server_name_selected' in params:
        return redirect(admin_servers_states)

    techs = list(technology.get_all_technologies(params['server_name_selected']))
    return render(request, 'admin_technology.html', {'technologies': techs})


@staff_member_required
def admin_geography(request):
    params = request_params(request)
    if not 'server_name_selected' in params or not 'target' in params:
        return redirect(admin_servers_states)

    server = params['server_name_selected']
    geography_table = []


    # #### GLOBAL LISTS #### #
    # /!\ Slow to generate for systems and nearly impossible for systems, way too big to display correctly

    if params['target'] == "sectors":
        geography_table = sectors.get_all_sectors(server)
        # Remove data too heavy
        for sector in geography_table:
            if 'systems_coordinates' in sector:
                del sector['systems_coordinates']

    if params['target'] == "systems":
        # Remove clutter from system composition dictionary for better display
        geography_table_cluttered = systems.get_all_systems(server)
        geography_table = []
        for system in geography_table_cluttered:
            system['system_coordinates'] = str(system['system_coordinates']).replace("{'", '')\
                                                                            .replace("': '", ' : ')\
                                                                            .replace("', '", '<br>')\
                                                                            .replace("'}", '')
            geography_table.append(system)

    if params['target'] == "coordinates":
        geography_table = coordinates.get_all_coordinates(server)


    # #### SPECIFIC LIST #### #
    # Search according to _id (seed) and display every sub-elements presents in it

    if params['target'].isnumeric():
        parent_seed = int(params['target'])

        #if


    return render(request, 'admin_geography.html', {'geography_table': geography_table, 'target': params['target']})
