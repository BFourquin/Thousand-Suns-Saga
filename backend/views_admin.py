import logging

from django.dispatch import receiver
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth.decorators import user_passes_test
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from django.contrib.auth import login
from django.core.paginator import Paginator
from hijack.signals import hijack_started, hijack_ended


from anticheat.rules import scans_status
from backend.login import throttled_authenticate
from backend.models import to_id
from backend.utils import request_params
from database.schemas import server_schema
from game.models import Coordinate, Sector, System
from data import admin, server_details, user, technology, sectors, systems, coordinates, map_generator, forums

logger = logging.getLogger(__name__)

# The same rule as admin_login : the staff moderates the game, the administration is for the superusers
superuser_required = user_passes_test(lambda user: user.is_active and user.is_superuser, login_url='/admin_login/')


def admin_login(request):

    login_error = None

    if request.method == 'POST':
        user, login_error = throttled_authenticate(request)
        if user is not None and user.is_superuser:
            login(request, user)
            return redirect('admin_main_dashboard')

    return render(request, 'admin/admin_login.html', {'login_error': login_error})


@superuser_required
def admin_main_dashboard(request):
    return render(request, 'admin/admin_main_dashboard.html')



########################################################################################################################
# GENERAL ADMINISTRATION PAGES
########################################################################################################################

# ACCOUNTS
@superuser_required
def admin_user_accounts(request):
    return render(request, 'admin/admin_user_accounts.html', {'user_accounts': user.get_all_users(strify=True)})


@superuser_required
def admin_player_control(request):
    return render(request, 'admin/admin_player_control.html', {'players': User.objects.order_by('username')})


@receiver(hijack_started)
def log_hijack_started(sender, hijacker, hijacked, **kwargs):
    logger.warning('Hijack : %s takes control of the account of %s', hijacker.username, hijacked.username)


@receiver(hijack_ended)
def log_hijack_ended(sender, hijacker, hijacked, **kwargs):
    logger.warning('Hijack : %s gives back the account of %s', hijacker.username, hijacked.username)


@superuser_required
def admin_user_details(request):
    id = request_params(request)['id']
    user_account = user.get_user_by_id(id)
    return render(request, 'admin/admin_user_details.html', {'user': user_account})


# ######################################################################################################################
# SERVERS STATES

@superuser_required
def admin_servers_states(request):
    return render(request, 'admin/admin_servers_states.html', {'servers_details': server_details.get_all_servers_details()})


BOOLEAN_VALUES = ('true', 'false')
EDITABLE_SERVER_PARAMS = {'status': server_details.server_status, 'admin_only_visibility': BOOLEAN_VALUES, 'exclusive': BOOLEAN_VALUES}


@require_POST
@superuser_required
def admin_servers_states_edit(request):
    param, value = request.POST.get('type'), request.POST.get('value')
    if value in EDITABLE_SERVER_PARAMS.get(param, ()):
        value = value == 'true' if value in BOOLEAN_VALUES else value
        server_details.change_server_param(request.POST.get('server_name'), param, value)
        server_details.refresh_servers_menu()
    return redirect(admin_servers_states)


########################################################################################################################
# SERVER SPECIFIC ADMINISTRATION
########################################################################################################################

GEOGRAPHY_PAGE_SIZE = 100
GEOGRAPHY_TABLES = {'sectors': Sector, 'systems': System, 'coordinates': Coordinate}


@superuser_required
def admin_technology(request):
    params = request_params(request)
    if not 'server_name_selected' in params:
        return redirect(admin_servers_states)

    techs = list(technology.get_all_technologies(params['server_name_selected']))
    return render(request, 'admin/admin_technology.html', {'technologies': techs})


# ######################################################################################################################
# MESSAGES REPORTED BY THE PLAYERS

@superuser_required
def admin_message_flags(request):
    # All the servers, or the one chosen in its own menu
    selected_server = request.GET.get('server_name_selected')
    if selected_server and not server_details.get_server_details(selected_server):
        return redirect(admin_servers_states)

    if request.method == 'POST':
        server = request.POST.get('server')
        if server_details.get_server_details(server):
            if request.POST.get('action') == 'close':
                forums.close_flag(server, request.POST.get('flag_id'), request.user.username)
            elif request.POST.get('action') == 'delete_message':
                forums.delete_flagged_message(server, request.POST.get('flag_id'), request.user.username)
        return redirect(request.get_full_path())

    more_than = request.GET.get('more_than', '')
    more_than = int(more_than) if more_than.isdecimal() else 0
    servers = [selected_server] if selected_server else server_details.get_servers_names(admin_visibility=True)
    return render(request, 'admin/admin_message_flags.html', {
        'flags': forums.get_reported_messages(servers, more_than), 'more_than': more_than})


# ######################################################################################################################
# ANTICHEAT

@superuser_required
def admin_cheat_alerts(request):
    if request.method == 'POST':
        alert_id = to_id(request.POST.get('alert_id'))
        if alert_id:
            admin.set_alert_open(alert_id, request.POST.get('action') == 'reopen', request.user.username)
        return redirect('admin_cheat_alerts')

    return render(request, 'admin/admin_cheat_alerts.html', {'alerts': admin.get_alerts(), 'scans': scans_status()})


# ######################################################################################################################
# GEOGRAPHY

@superuser_required
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
                if key in ('id', 'seed', 'sector_id', 'system_id'):
                    entry[key] = format_html('<a href="?server_name_selected={}&amp;target={}">{}</a>', server, value, value)


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
                geo_uncluttered['system_coordinates'] = format_html_join(
                    mark_safe('<br>'), '<a href="?server_name_selected={}&amp;target={}">{}</a> : {}',
                    ((server, seed, seed, name) for seed, name in geo['system_coordinates'].items()))

            systems_table.append(geo_uncluttered)
        return systems_table

    # #### GLOBAL LISTS #### #

    geography_page = None
    if params['target'] in GEOGRAPHY_TABLES:
        with server_schema(server):
            rows = GEOGRAPHY_TABLES[params['target']].objects.order_by('seed')
            geography_page = Paginator(rows, GEOGRAPHY_PAGE_SIZE).get_page(params.get('page'))
            geography_table = [row.as_dict() for row in geography_page.object_list]

    if params['target'] == "sectors":
        geography_table = unclutter_sectors_table(geography_table)

    if params['target'] == "systems":
        geography_table = unclutter_geography_table(geography_table)


    # #### SPECIFIC LIST #### #
    # Search according to the seed and display every sub-elements presents in it

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
                                                          'seed_type': seed_type, 'geography_page': geography_page})
