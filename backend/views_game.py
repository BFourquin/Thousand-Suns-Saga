from django.template.response import TemplateResponse
from django.shortcuts import redirect, HttpResponseRedirect
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.utils import timezone


import data.user
import data.themes
from backend.models import to_id
from backend.decorators import add_cycle_info, log_player_action, commandant_required
from backend.utils import request_params, parameters_presents, get_request_user
from data import server_details, user, commandant, systems, technology, sectors, systems, coordinates, map_generator, cycles
from data.report import get_commandant_reports, get_report, delete_report, change_report_status, \
    mark_all_reports_as_read, update_nb_unread_reports
from data.colonies import get_colonies_controlled_by_commandant, get_colonies_at_coordinates
from data.commandant import get_commandants
from data.economy import cycle_balance
from data.resources import get_all_resources_parameters, get_resources_categories, get_resources_subcategories
from data.names import localized_name


########################################################################################################################
# LOGGED NON-GAME AREA

@login_required(login_url='/player_login/')
def user_account(request):

    user = get_request_user(request)

    if request.method == 'POST':
        params = request.POST

        if 'language' in params and params['language'] in ('fr', 'en'):
            data.user.update_user(user, 'language', params['language'])

        if 'dark_mode' in params and params['dark_mode'] in ('true', 'false'):
            data.user.update_user(user, 'dark_mode', params['dark_mode'] == 'true')

        if 'theme' in params and data.themes.is_valid_theme(params['theme']):
            data.user.update_user(user, 'theme', params['theme'])

        return redirect('/user_account/')

    accounts = []
    for account_server, account_id in user['accounts']:
        account = data.commandant.get_commandant(account_server, account_id)
        if account:
            accounts.append(account)

    dead_accounts = []
    for account_server, account_id in user['dead_accounts']:
        dead_account = data.commandant.get_commandant(account_server, account_id)
        if dead_account:
            dead_accounts.append(dead_account)

    return TemplateResponse(request, 'game/user_account.html',
                            {'current_user': dict(user), 'accounts': accounts, 'dead_accounts': dead_accounts,
                             'themes': data.themes.themes_for_template()})



@login_required(login_url='/player_login/')
def create_commandant(request):

    params = request_params(request)

    if not 'server_name' in params:
        return redirect('/user_account/')

    server = server_details.get_server_details(params['server_name'])

    if not server:
        return redirect('servers_list')

    server['open_since_days'] = (timezone.now() - server['opening_date']).days

    return TemplateResponse(request, 'game/create_commandant.html', {'server': server})



@login_required(login_url='/player_login/')
def commandant_login(request):

    params = request_params(request)

    if not parameters_presents(('server', 'commandant_id'), params):
        return redirect('/user_account/')

    user = get_request_user(request)
    commandant_id = params['commandant_id']
    server_name = params['server']

    if (server_name, to_id(commandant_id)) not in user['accounts']:
        ... # TODO log suspicious use to another player's commandant
        return redirect('/user_account/')

    commandant = data.commandant.get_commandant(server_name, commandant_id)
    if not commandant:
        return redirect('/user_account/')

    data.user.update_user(user, 'playing_on_server', server_name)
    data.user.update_user(user, 'playing_on_commandant', commandant_id)

    return redirect('/geography_system/', {'system_id': commandant['native_system']})


########################################################################################################################
#  IN GAME AREA ########################################################################################################
########################################################################################################################



@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def cycle_monitoring(request, server, commandant):

    params = request_params(request)

    # Admin / MG display and actions
    display_admin_and_gm_info = False

    if request.user.is_authenticated and request.user.is_staff:  # TODO check if player is a game master for this server
        display_admin_and_gm_info = True
    if display_admin_and_gm_info and request.method == 'POST':
        if 'admin_action' in params and params['admin_action'] == 'end_cycle':
            cycles.end_cycle(server)
            return HttpResponseRedirect(request.path_info)
        if 'admin_mark_as_absent' in params:
            cycles.mark_commandant_cycle_absent(server, params['admin_mark_as_absent'])
            return HttpResponseRedirect(request.path_info)


    # Commandants status

    if request.method == 'POST' and 'commandant_cycle_status' in params:
        if params['commandant_cycle_status'] == 'commandant_cycle_finished':
            cycles.mark_commandant_cycle_finished(server, commandant['id'])
        elif params['commandant_cycle_status'] == 'commandant_cycle_playing':
            cycles.mark_commandant_cycle_playing(server, commandant['id'])
        return HttpResponseRedirect(request.path_info)

    if request.method == 'POST' and 'commandant_cycle_presence' in params:
        if params['commandant_cycle_presence'] == 'commandant_cycle_absent':
            cycles.mark_commandant_cycle_absent(server, commandant['id'])
        elif params['commandant_cycle_presence'] == 'commandant_cycle_present':
            cycles.mark_commandant_cycle_present(server, commandant['id'])
        return HttpResponseRedirect(request.path_info)


    # All needed cycles infos are already available in the decorator @add_cycle_info
    return TemplateResponse(request, 'game/cycle_monitoring.html', {'server': server, 'display_admin_and_gm_info': display_admin_and_gm_info})


########################################################################################################################


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def reports(request, server, commandant):

    params = request_params(request)

    if request.method == 'POST' and 'action' in params:

        # Mark all as read global button
        if params['action'] == 'mark_all_as_read':
            mark_all_reports_as_read(server, commandant['id'], params['category'] if 'category' in params else 'all')
            update_nb_unread_reports(server, commandant['id'])
            return redirect('/reports/')

        if 'reports[]' in params:

            # Get all selected reports
            if isinstance(params['reports[]'], str):  # Only one report selected instead of list : convert to list
                params['reports[]'] = [params['reports[]']]

            for report_id in params['reports[]']:
                # Delete button
                if params['action'] == 'delete':
                    delete_report(server, report_id, commandant['id'])

                # Read button
                if params['action'] == 'read':
                    change_report_status(server, report_id, commandant['id'], 'read')
                # Unread button
                if params['action'] == 'unread':
                    change_report_status(server, report_id, commandant['id'], 'unread')

                # Archive button
                if params['action'] == 'archive':
                    change_report_status(server, report_id, commandant['id'], 'archived')
                # Unarchive button
                if params['action'] == 'unarchive':
                    change_report_status(server, report_id, commandant['id'], 'read')

        update_nb_unread_reports(server, commandant['id'])


    filter_category = params['category'] if 'category' in params else 'all'
    filter_status = params['status'] if 'status' in params else 'not_archived'
    search_text = params['search_text'] if 'search_text' in params else None

    reports, nb_unread_reports = get_commandant_reports(server, commandant['id'],
                                                        filter_status=filter_status, filter_category=filter_category,
                                                        search_text=search_text)

    # TODO remove graphic test reports <--
    """report =   {'id': '66f5689febe0ed0d929f3ca1',
                'status': 'unread',
                'owner': None,
                'category': 'other',
                'category_icon': 'fa-file-alt',

                'datetime': '14/06/2412 11h35',

                'illustration': 'images/report/command_center.png',

                'title': 'Colonisation réussie',
                'message': "La mission de colonisation de ce monde est un succès, mais votre mission ne fait que commencer."
                           "Un peuple tout entier attend vos ordres pour faire prospérer cette modeste colonie en une véritable civilisation à part entère !",

                'sender': 'Aurelia de Siravedra',
                'sender_image': 'images/Aurelia.png',
               }
    reports.append(report.copy());reports.append(report.copy())
    report['status'] = 'read';reports.append(report.copy());reports.append(report.copy())
    report['status'] = 'archived';reports.append(report.copy());reports.append(report.copy())"""
    # TODO remove graphic test reports -->

    # Pagination
    paginator = Paginator(reports, 5)  # TODO report per page in user settings
    page_number = params['page'] if 'page' in params else 1
    reports = paginator.get_page(page_number)

    return TemplateResponse(request, 'game/reports.html',
                            {'server': server, 'reports': reports,
                             'nb_unread_reports': nb_unread_reports,
                             'status': filter_status, 'category': filter_category,
                             'search_text': search_text, 'page': page_number
                             })



@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def report(request, server, commandant):

    params = request_params(request)

    if not 'report_id' in params:
        return redirect('/reports/')

    report = get_report(server, params['report_id'], commandant['id'])
    if not report:
        return redirect('/reports/')

    change_report_status(server, params['report_id'], commandant['id'], 'read')

    return TemplateResponse(request, 'game/report.html', {'server': server, 'report': report})


########################################################################################################################


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def geography_system(request, server, commandant):

    params = request_params(request)

    # TODO check if commandant has vision on the system

    system = None
    system_searched = False
    if params.get('system_id'):
        system_searched = True
        system = systems.get_system_by_seed(server, params['system_id'].strip())
    elif params.get('sector_id') and params.get('pos_y') and params.get('pos_x'):
        system_searched = True
        system = systems.get_system_by_position(server, params['sector_id'].strip(),
                                                params['pos_y'].strip().zfill(3), params['pos_x'].strip().zfill(3))

    system_not_found = system_searched and system is None
    if system is None:
        system = systems.get_system_by_seed(server, commandant['native_system'])

    system_coordinates = [coordinates.add_display_info(coordinate)
                          for coordinate in coordinates.get_coordinates_of_system(server, system)]
    coordinates_by_id = {coordinate['id']: coordinate for coordinate in system_coordinates}
    for coordinate in system_coordinates:
        coordinate['colonies'] = []

    # Who is settled on each coordinate
    colonies = get_colonies_at_coordinates(server, list(coordinates_by_id))
    owners = {owner['id']: owner for owner in
              get_commandants(server, [colony['owner'] for colony in colonies])}

    for colony in colonies:
        owner = owners.get(colony['owner'], {})
        colony['is_mine'] = colony['owner'] == commandant['id']
        colony['owner_name'] = owner.get('commandant_name', '')
        colony['civilisation_name'] = owner.get('civilisation_name', '')
        located_on = coordinates_by_id[colony['coordinate']]
        located_on['colonies'].append(colony)
        located_on['has_my_colony'] = located_on.get('has_my_colony') or colony['is_mine']

    return TemplateResponse(request, 'game/geography_system.html',
                            {'server': server, 'system': system,
                             'system_coordinates': system_coordinates,
                             'star': system_coordinates[0],
                             'system_not_found': system_not_found})


########################################################################################################################




@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def resources(request, server, commandant):

    params = request_params(request)

    selected_category = params['selected_category'] if 'selected_category' in params else 'all'
    language = get_request_user(request)['language']


    resources_declaration = get_all_resources_parameters(server)
    forecast = cycle_balance(server, commandant['id'], commandant['resources'])

    # Reformat with only useful info
    resources_table = []

    for resource in resources_declaration:

        if selected_category != 'all' and resource['category'] != selected_category:
            continue

        resource_name = resource['internal_name']
        if resource_name not in commandant['resources'].keys():
            ... # continue  # TODO display undiscovered resources greyed instead of hiding them ?

        # What is needed for the next cycle, even when the stock can't cover it
        produced = forecast['produced'][resource_name]
        needed = forecast['consumed'][resource_name] + forecast['missing'][resource_name]

        resources_table.append({
            'name': localized_name(resource, language),
            'icon': resource['icon'],
            'stock': commandant['resources'][resource_name] if resource_name in commandant['resources'] else 0,
            'produced': produced,
            'consumed': needed,
            'balance': produced - needed,
            'self_sustainability': produced / needed * 100 if needed else None,
            'decree': '',
            'effect': '',
        })

    resources_categories = list(get_resources_categories(server))
    for category in resources_categories:
        category['name'] = localized_name(category, language)

    return TemplateResponse(request, 'game/resources.html',
                            {'server': server, 'resources': resources_table,
                             'selected_category': selected_category, 'resources_categories': resources_categories})

