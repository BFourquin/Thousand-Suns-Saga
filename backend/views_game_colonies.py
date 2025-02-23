from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
import datetime

import data.user
from backend.utils import request_params, parameters_presents, get_active_server_and_commandant_from_request
from data import server_details, user, commandant, systems, technology, sectors, systems, coordinates, map_generator
from data.user import get_user_by_name, get_user_by_object_id, update_user
from data.report import get_commandant_reports, get_report_by_object_id, delete_report, change_report_status, \
    mark_all_reports_as_read, update_nb_unread_reports
from data.colonies import get_colonies_controlled_by_commandant, get_colony
from data.resources import get_all_resources_parameters, get_resources_categories, get_resources_subcategories



@login_required(login_url='/player_login/')
def colonies(request):

    params = request_params(request)
    server, commandant = get_active_server_and_commandant_from_request(request)

    if not server or not commandant:
        redirect('/user_account/')

    filter_category = params['category'] if 'category' in params else 'all'
    filter_marker = params['marker'] if 'marker' in params else 'all'
    search_text = params['search_text'] if 'search_text' in params else None

    colonies = get_colonies_controlled_by_commandant(server, commandant['_id'], add_coo_image=True)

    colonies.append(colonies) # TODO remove, visual test

    return render(request, 'game/colonies.html', {'server': server, 'colonies': colonies,
                                                  'marker': filter_marker, 'category': filter_category,
                                                  'search_text': search_text
                                                  })



@login_required(login_url='/player_login/')
def colony(request):

    params = request_params(request)
    server, commandant = get_active_server_and_commandant_from_request(request)

    filter_districts = params['districts_type'] if 'districts_type' in params else 'all'

    if not server or not commandant:
        redirect('/user_account/')
    if 'colony_id' not in params:
        redirect('/colonies/')

    try:
        colony_dict = get_colony(server, params['colony_id'], add_coo_image=True)
    except Exception as e:
        redirect('/colonies/')


    return render(request, 'game/colony.html', {'server': server, 'colony': colony_dict,
                                                'districts_type': filter_districts,
                                                })


