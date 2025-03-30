from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from bson.objectid import ObjectId
import datetime


import data.user
from backend.utils import request_params, parameters_presents, get_active_server_and_commandant_from_request
from data import server_details, user, commandant, systems, technology, sectors, systems, coordinates, map_generator
from data.user import get_user_by_name, get_user_by_object_id, update_user
from data.report import get_commandant_reports, get_report_by_object_id, delete_report, change_report_status, \
    mark_all_reports_as_read, update_nb_unread_reports
from data.colonies import get_colonies_controlled_by_commandant
from data.resources import get_all_resources_parameters, get_resources_categories, get_resources_subcategories


########################################################################################################################
# PUBLIC AREA

@login_required(login_url='/player_login/')
def user_account(request):

    user = get_user_by_name(str(request.user))
    params = request_params(request)

    if 'language' in params and params['language'] in ('fr', 'en'):
        data.user.update_user(user, 'language', params['language'])

    if 'dark_mode' in params and params['dark_mode'] in ('true', 'false'):
        darkmode = params['dark_mode'] == 'true'
        data.user.update_user(user, 'dark_mode', darkmode)

    accounts = []
    for account_id in user['accounts']:
        account = data.commandant.get_commandant_from_any_server(_id=account_id)
        if account:
            accounts.append(account)

    dead_accounts = user['dead_accounts']
    for account_id in user['dead_accounts']:
        dead_account = data.commandant.get_commandant_from_any_server(_id=account_id)
        if dead_account:
            dead_accounts.append(dead_account)

    user = get_user_by_name(str(request.user))  # Get it again in case of parameter changed

    return render(request, 'game/user_account.html', {'current_user': dict(user),
                                                      'accounts': accounts, 'dead_accounts': dead_accounts})



@login_required(login_url='/player_login/')
def create_commandant(request):

    params = request_params(request)

    if not 'server_name' in params:
        print(params)
        return redirect('/user_account/')

    server = server_details.get_server_details(params['server_name'])

    if not server:
        return redirect('servers_list')

    server['open_since_days'] = (datetime.datetime.now() - server['opening_date']).days

    return render(request, 'game/create_commandant.html', {'server': server})



@login_required(login_url='/player_login/')
def commandant_login(request):

    params = request_params(request)

    if not parameters_presents(('server', 'commandant_id'), params):
        return redirect('/user_account/')

    user = get_user_by_name(str(request.user))
    commandant_id = params['commandant_id']
    server_name = params['server']
    server = data.server_details.get_server_details('TSS_'+server_name)

    if ObjectId(commandant_id) not in user['accounts']:
        # Check if suspicious connection to another player's commandant
        if data.commandant.get_commandant_by_object_id(server_name, commandant_id):
            ... # TODO log suspicious use to another player's commandant
        return redirect('/user_account/')

    commandant = data.commandant.get_commandant_by_object_id(server_name, commandant_id)
    if not commandant:
        return redirect('/user_account/')

    data.user.update_user(user, 'playing_on_server', server_name)
    data.user.update_user(user, 'playing_on_commandant', commandant_id)

    return redirect('/geography_system/', {'system_id': commandant['native_system']})


@login_required(login_url='/player_login/')
def user_account(request):

    user = get_user_by_name(str(request.user))
    params = request_params(request)

    if 'language' in params and params['language'] in ('fr', 'en'):
        data.user.update_user(user, 'language', params['language'])

    if 'dark_mode' in params and params['dark_mode'] in ('true', 'false'):
        darkmode = params['dark_mode'] == 'true'
        data.user.update_user(user, 'dark_mode', darkmode)

    accounts = []
    for account_id in user['accounts']:
        account = data.commandant.get_commandant_from_any_server(_id=account_id)
        if account:
            accounts.append(account)

    dead_accounts = user['dead_accounts']
    for account_id in user['dead_accounts']:
        dead_account = data.commandant.get_commandant_from_any_server(_id=account_id)
        if dead_account:
            dead_accounts.append(dead_account)

    user = get_user_by_name(str(request.user))  # Get it again in case of parameter changed

    return render(request, 'game/user_account.html', {'current_user': dict(user),
                                                      'accounts': accounts, 'dead_accounts': dead_accounts})


########################################################################################################################
#  IN GAME AREA


@login_required(login_url='/player_login/')
def reports(request):

    params = request_params(request)
    server, commandant = get_active_server_and_commandant_from_request(request)

    if not server or not commandant:
        return redirect('/user_account/')

    if 'action' in params:

        # Mark all as read global button
        if params['action'] == 'mark_all_as_read':
            mark_all_reports_as_read(server, commandant['_id'], params['category'] if 'category' in params else 'all')
            update_nb_unread_reports(server, commandant['_id'])
            return redirect('/reports/')

        if 'reports[]' in params:

            # Get all selected reports
            if isinstance(params['reports[]'], str):  # Only one report selected instead of list : convert to list
                params['reports[]'] = [params['reports[]']]

            for report_id in params['reports[]']:
                try:
                    # Delete button
                    if params['action'] == 'delete':
                        delete_report(server, report_id)

                    # Read button
                    if params['action'] == 'read':
                        change_report_status(server, report_id, 'read')
                    # Unread button
                    if params['action'] == 'unread':
                        change_report_status(server, report_id, 'unread')

                    # Archive button
                    if params['action'] == 'archive':
                        print(report_id)
                        change_report_status(server, report_id, 'archived')
                    # Unarchive button
                    if params['action'] == 'unarchive':
                        change_report_status(server, report_id, 'read')

                except TypeError:  # Report not existing (already deleted):
                    continue

        update_nb_unread_reports(server, commandant['_id'])


    filter_category = params['category'] if 'category' in params else 'all'
    filter_status = params['status'] if 'status' in params else 'not_archived'
    search_text = params['search_text'] if 'search_text' in params else None

    reports, nb_unread_reports = get_commandant_reports(server, commandant['_id'],
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

    return render(request, 'game/reports.html', {'server': server, 'reports': reports,
                                                 'nb_unread_reports': nb_unread_reports,
                                                 'status': filter_status, 'category': filter_category,
                                                 'search_text': search_text, 'page': page_number
                                                 })



@login_required(login_url='/player_login/')
def report(request):

    params = request_params(request)
    server, commandant = get_active_server_and_commandant_from_request(request)

    if not server or not commandant:
        return redirect('/user_account/')

    if not 'report_id' in params:
        return redirect('/reports/')

    report = get_report_by_object_id(server, params['report_id'])
    if not report:
        return redirect('/reports/')

    change_report_status(server, params['report_id'], 'read')

    return render(request, 'game/report.html', {'server': server, 'report': report})


########################################################################################################################


@login_required(login_url='/player_login/')
def geography_system(request):

    params = request_params(request)
    server, commandant = get_active_server_and_commandant_from_request(request)

    if not server or not commandant:
        return redirect('/user_account/')

    # TODO check if commandant has vision on the system


    if 'system_id' in params:
        system_id = params['system_id']
    elif parameters_presents(('system_id', 'pos_y', 'pos_x'), params):
        system_id = None  # TODO system view from composite coordinate
        #get_system_by_position(server, sector_id, y, x)
    else:
        system_id = commandant['native_system']

    system = systems.get_system_by_seed(server, system_id)
    system['id'] = system['_id']

    system_coordinates = []
    for coordinate in system['system_coordinates'].keys():
        coo = data.coordinates.get_coordinate(server, coordinate)
        coo['image'] = 'images/placeholder/'+coo['type']+'.png'  # TODO get planet image

        system_coordinates.append(coo)

    nb_rows_display = 1 + (len(system_coordinates)-1)//8
    display_nb_coos_per_rows = len(system_coordinates)//nb_rows_display


    return render(request, 'game/geography_system.html', {'server': server, 'system': system,
                                                          'system_coordinates': system_coordinates,
                                                          'display_nb_coos_per_rows': display_nb_coos_per_rows})


########################################################################################################################




@login_required(login_url='/player_login/')
def resources(request):

    params = request_params(request)
    server, commandant = get_active_server_and_commandant_from_request(request)

    if not server or not commandant:
        return redirect('/user_account/')

    selected_category = params['selected_category'] if 'selected_category' in params else 'all'


    resources_declaration = get_all_resources_parameters(server)
    commandant_resources = None
    commandant_resources_stats = None
    global_resources_stats = None

    # Reformat with only useful info
    resources_table = []

    for resource in resources_declaration:

        if selected_category != 'all' and resource['category'] != selected_category:
            continue

        resource_name = resource['internal_name']
        if resource_name not in commandant['resources'].keys():
            ... # continue  # TODO display undiscovered resources greyed instead of hiding them ?


        resources_table.append({
            'name': resource['name_' + 'fr'],  # TODO translation
            'icon': resource['icon'],
            'stock': commandant['resources'][resource_name] if resource_name in commandant['resources'] else 0,
            'max_storage': 20000,
            'buy_percent': 20,
            'sell_percent': 60,
            'produced': 178,
            'consumed': 80,
            'balance': 98,
            'self_sustainability': 223,
            'global_supply': 72,
            'decree': '',
            'effect': '',
        })

    resources_categories = get_resources_categories(server)
    # resources_categories['name'] = resources_categories['name_fr']  # TODO auto-translation

    return render(request, 'game/resources.html', {'server': server, 'resources': resources_table,
                                                   'selected_category': selected_category,
                                                   'resources_categories': resources_categories})

