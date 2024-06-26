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


def admin_login(request):

    params = request_params(request)

    if parameters_presents(('username', 'password'), params):

        username = params['username']
        password = params['password']
        user = authenticate(username=username, password=password)
        if user is not None and user.is_superuser and user.is_active:
            login(request, user)
            return redirect('admin_main_dashboard')

    return render(request, 'admin/admin_login.html')


@staff_member_required(login_url='/admin_login/')
def bokeh_exemple(request):

    if not request.user.is_superuser:
        return render(request, 'admin/admin_login.html')

    # create a plot
    plot = figure(plot_width=400, plot_height=400)

    # add a circle renderer with a size, color, and alpha
    plot.circle([1, 2, 3, 4, 5], [6, 7, 2, 4, 5], size=20, color="navy", alpha=0.5)
    bokeh_script, bokeh_div = components(plot)

    return render(request, 'admin/bokeh_exemple.html', {'bokeh_script': bokeh_script, 'bokeh_div': bokeh_div})


@staff_member_required(login_url='/admin_login/')
def admin_main_dashboard(request):
    if not request.user.is_superuser:
        return render(request, 'admin/admin_login.html')
    return render(request, 'admin/admin_main_dashboard.html')



def test_hijack(request):

    from django.contrib.auth.models import User

    target = User.objects.get(id=2)

    return render(request, 'admin/test_hijack.html', {'another_user': target})


########################################################################################################################
# GENERAL ADMINISTRATION PAGES
########################################################################################################################

# ACCOUNTS
@staff_member_required(login_url='/admin_login/')
def admin_user_accounts(request):
    return render(request, 'admin/admin_user_accounts.html', {'user_accounts': user.get_all_users(strify=True)})


@staff_member_required(login_url='/admin_login/')
def admin_user_details(request):
    id = request_params(request)['id']
    user_account = user.get_user_by_id(id)
    user_account['objectid'] = user_account['_id']
    return render(request, 'admin/admin_user_details.html', {'user': user_account})


# ######################################################################################################################
# SERVERS STATES

@staff_member_required(login_url='/admin_login/')
def admin_servers_states(request):
    return render(request, 'admin/admin_servers_states.html', {'servers_details': server_details.get_all_servers_details()})


@staff_member_required(login_url='/admin_login/')
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


@staff_member_required(login_url='/admin_login/')
def admin_technology(request):
    params = request_params(request)
    if not 'server_name_selected' in params:
        return redirect(admin_servers_states)

    techs = list(technology.get_all_technologies(params['server_name_selected']))
    return render(request, 'admin/admin_technology.html', {'technologies': techs})


# ######################################################################################################################
# GEOGRAPHY

@staff_member_required(login_url='/admin_login/')
def admin_geography(request):
    params = request_params(request)
    if not 'server_name_selected' in params or not 'target' in params:
        return redirect(admin_servers_states)

    server = params['server_name_selected']
    geography_table = []

    def add_urls_on_seeds(geography_table):
        # Search all geography table's seeds and inject html link to it
        for entry in geography_table:
            for key, value in entry.items():
                if key in ('_id', 'seed', 'sector_id', 'system_id'):
                    entry[key] = '<a href="' \
                                 '?server_name_selected=' + server + \
                                 '&target=' + str(value) + '">' + str(value) + '</a>'


        return geography_table

    def unclutter_sectors_table(sectors_table):
        # Remove data too heavy
        for sector in sectors_table:
            if 'systems_coordinates' in sector:
                del sector['systems_coordinates']
        return sectors_table

    def unclutter_geography_table(geo_table_cluttered):
        # Remove clutter from geography dictionary for better display
        systems_table = []
        for geo in geo_table_cluttered:
            geo_uncluttered = geo.copy()
            if 'system_coordinates' in geo_uncluttered:
                geo_uncluttered['system_coordinates'] = str(geo['system_coordinates']).replace("{'", '')\
                                                                                    .replace("': '", ' : ')\
                                                                                    .replace("', '", '<br>')\
                                                                                    .replace("'}", '')
                for seed in geo['system_coordinates'].keys():
                    geo_uncluttered['system_coordinates'] = geo_uncluttered['system_coordinates'].replace(seed,
                                    '<a href="' \
                                    '?server_name_selected=' + server + \
                                    '&target=' + seed + '">' + seed + '</a>')

            systems_table.append(geo_uncluttered)
        return systems_table

    # #### GLOBAL LISTS #### #
    # /!\ Slow to generate for systems and nearly impossible for systems, way too big to display correctly

    if params['target'] == "sectors":
        geography_table = sectors.get_all_sectors(server)
        geography_table = unclutter_sectors_table(geography_table)

    if params['target'] == "systems":
        geography_table = systems.get_all_systems(server)
        geography_table = unclutter_geography_table(geography_table)

    if params['target'] == "coordinates":
        geography_table = coordinates.get_all_coordinates(server)


    # #### SPECIFIC LIST #### #
    # Search according to _id (seed) and display every sub-elements presents in it

    parent_table, parent_seed, seed_type = None, None, None
    if params['target'].isnumeric():
        parent_seed = int(params['target'])

        seed_type = map_generator.get_seed_type(parent_seed)

        if seed_type == "sector":

            parent_table = [sectors.get_sector_by_seed(server, parent_seed)]
            parent_table = unclutter_sectors_table(parent_table)

            geography_table = systems.get_systems_in_sector(server, parent_seed)
            geography_table = unclutter_geography_table(geography_table)

        elif seed_type == "system":
            parent_table = systems.get_system_by_seed(server, parent_seed)

            geography_table = []
            for coo_seed in parent_table['system_coordinates'].keys():
                geography_table.append(coordinates.get_coordinate(server, coo_seed))
            print(geography_table)
            geography_table = unclutter_geography_table(geography_table)

            if 'system_coordinates' in parent_table:
                del parent_table['system_coordinates']
            parent_table = unclutter_geography_table([parent_table])

        elif seed_type == "coordinate":
            parent_table = [coordinates.get_coordinate(server, parent_seed)]


    geography_table = add_urls_on_seeds(geography_table)
    if parent_table is not None:
        parent_table = add_urls_on_seeds(parent_table)


    return render(request, 'admin/admin_geography.html', {'geography_table': geography_table,'target': params['target'],
                                                          'parent_seed': parent_seed, 'parent_table': parent_table,
                                                          'seed_type': seed_type})
