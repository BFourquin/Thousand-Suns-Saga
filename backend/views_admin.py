import base64
import io
import logging
import secrets

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
from data import admin, schedule, server_details, user, technology, sectors, systems, coordinates, map_generator, forums

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
    servers = server_details.get_all_servers_details()
    for server in servers:
        server['schedule'] = schedule.schedule_state(server)
    return render(request, 'admin/admin_servers_states.html', {'servers_details': servers})


@require_POST
@superuser_required
def admin_unblock_schedule(request):
    schedule.unblock(request.POST.get('server_name'), request.user.username)
    return redirect(admin_servers_states)


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


# ######################################################################################################################
# MAP TRIALS : a map of the new generator, made in memory to find a good seed before creating a server. Nothing is saved.

# (label, least, most) of the numbers asked ; the empty ones take the value of the type of game
MAP_TRIAL_NUMBERS = {'players': ('Joueurs max', 2, 300), 'area_per_player': ('Surface par joueur', 2_000, 50_000),
                     'homes_per_cradle': ('Mondes natals par berceau', 2, 20)}


def png_data_url(picture):
    buffer = io.BytesIO()
    picture.save(buffer, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()


def map_trial_stats(sector):
    # (label, value, None or whether it looks good, what it means)
    from numpy import percentile
    m, expansion, cradles = sector.measures, sector.measures['expansion'], sector.measures['expansion_berceaux']
    spread = float(expansion.max() / expansion.min())
    deciles = float(percentile(expansion, 90) / percentile(expansion, 10))
    network = float((sector.comp == sector.main).mean())
    corridors = min(m['ouest_est'][0], m['nord_sud'][0])
    rows = [('Toile', f'{sector.W} × {sector.H} u', None, f'{sector.n} systèmes, {sector.n_cradles} berceau(x), {len(sector.homes)} mondes natals'),
            ('Galaxie agrandie', f'+{sector.grown - 1:.0%}', sector.grown <= 1.5, 'Pour loger les berceaux : une forme trop étroite fait grossir la carte'),
            ('Expansion, dernier / premier décile', f'{deciles:.2f}', deciles <= 1.7,
             'Valeur des systèmes plus proches de chaque monde natal que des autres : 1 serait parfait'),
            ('Expansion, plus riche / plus pauvre', f'{spread:.2f}', spread <= 2.5, 'Les extrêmes, souvent près des zones précieuses'),
            ('Écart entre berceaux', f'{cradles.max() / cradles.min():.2f}', cradles.max() / cradles.min() <= 1.3, 'Somme des mondes natals de chaque berceau'),
            ('Réseau principal', f'{network:.1%}', network >= 0.96, 'Part des systèmes joignables par vortex ; le reste est surtout dans le halo'),
            ('Couloirs ouest↔est / nord↔sud', f'{m["ouest_est"][0]} / {m["nord_sud"][0]}', corridors >= 3,
             'Chemins indépendants d\'un bord à l\'autre : 1 ou 2, c\'est un goulot'),
            ('Détour médian entre berceaux', f'{sorted(m["detours"])[len(m["detours"]) // 2]:.2f}' if m['detours'] else '-', None,
             'Chemin par vortex / ligne droite')]
    if m['vestiges']:
        rows.append(('Couloirs vers les vestiges', str(m['vestiges'][0]), m['vestiges'][0] >= 3, 'Mode chasse au trésor, depuis le bord ouest'))
    rows.append(('Durée', f'{sum(sector.timings.values()):.1f} s', None, ''))
    return rows


@superuser_required
def admin_map_trial(request):
    from geography.experiments import zone_map_prototype as maps  # numpy and Pillow : only loaded by this page

    post = request.POST
    form = {'gameplay': post.get('gameplay', 'saga'), 'seed': post.get('seed', '').strip()[:40],
            'vestiges': 'vestiges' in post, **{name: post.get(name, '').strip() for name in MAP_TRIAL_NUMBERS}}
    context = {'form': form, 'game_types': maps.GAME_TYPES, 'numbers': MAP_TRIAL_NUMBERS}
    if request.method == 'POST':
        errors, values = [], {}
        if form['gameplay'] not in maps.GAME_TYPES:
            errors.append('Type de partie inconnu')
        for name, (label, least, most) in MAP_TRIAL_NUMBERS.items():
            if not form[name] and name != 'players':
                values[name] = maps.GAME_TYPES.get(form['gameplay'], maps.GAME_TYPES['saga'])[name]
            elif form[name].isdecimal() and least <= int(form[name]) <= most:
                values[name] = int(form[name])
            else:
                errors.append(f'{label} : un nombre entier de {least} à {most}')
        context['errors'] = errors
        if not errors:
            seed = form['seed'] or str(secrets.randbelow(900_000) + 100_000)
            sector = maps.generate(seed, values.pop('players'), vestiges=form['vestiges'], **values)
            blank, zones = maps.render(sector)
            context['result'] = {
                'seed': seed, 'stats': map_trial_stats(sector), 'report': maps.report(sector),
                'pictures': [(title, png_data_url(picture), f'carte_{seed}_{name}.png') for title, name, picture in (
                    ('Zones', 'zones', zones), ('Liens vortex', 'liens', maps.render_links(sector)), ('Vierge', 'vierge', blank))]}
    return render(request, 'admin/admin_map_trial.html', context)


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
