from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required


from backend.decorators import add_cycle_info, log_player_action, commandant_required
from backend.utils import request_params, get_language, commandant_owns_colony
from data import server_details, user, commandant, systems, technology, sectors, systems, coordinates, map_generator
from data.user import get_user_by_name, get_user_by_object_id, update_user
from data.report import get_commandant_reports, get_report_by_object_id, delete_report, change_report_status, \
    mark_all_reports_as_read, update_nb_unread_reports
from data.colonies import get_colonies_controlled_by_commandant, get_colony
from data.districts import get_district
from data.districts_types import get_district_type, get_all_districts_types, get_all_buildable_districts_types
from data.resources import get_all_resources_parameters, get_resources_categories, get_resources_subcategories
from data.buildings import get_buildings
from data.names import localized_name



@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def colonies(request, server, commandant):

    params = request_params(request)

    filter_category = params['category'] if 'category' in params else 'all'
    filter_marker = params['marker'] if 'marker' in params else 'all'
    search_text = params['search_text'] if 'search_text' in params else None

    colonies = get_colonies_controlled_by_commandant(server, commandant['_id'], add_coo_image=True)

    return TemplateResponse(request, 'game/colonies.html',
                            {'server': server, 'colonies': colonies,
                             'marker': filter_marker, 'category': filter_category,
                             'search_text': search_text
                             })



@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def colony(request, server, commandant):

    params = request_params(request)
    if not commandant_owns_colony(commandant, params.get('colony_id')):
        return redirect('/colonies/')

    filter_districts = params['filter_districts'] if 'filter_districts' in params else 'all'

    colony_dict = get_colony(server, params['colony_id'], add_coo_image=True)
    colony_dict['id'] = colony_dict['_id']

    buildable_districts = get_all_buildable_districts_types(server, commandant, get_language(request))

    districts = []
    for district_id in colony_dict['districts']:
        district = get_district(server, district_id)  # Specific district info
        if district is None:
            continue  # Reference left by a district deleted before the fix of delete_district : the page must still open
        district.update(get_district_type(server, district['district_type']))  # Global district values
        district['id'] = str(district_id)
        district['name'] = localized_name(district, get_language(request))
        district['buildings'] = get_buildings(server, district['buildings_ids'], append_building_type=True)
        for building in district['buildings']:
            building['name'] = localized_name(building, get_language(request))
        district['free_districts_slots'] = district['districts_slots'] - len(colony_dict['districts']) + 1

        districts.append(district)



    return TemplateResponse(request, 'game/colony.html',
                            {'server': server, 'colony': colony_dict,
                             'districts': districts, 'filter_districts': filter_districts,
                             'buildable_districts': buildable_districts,
                             })


