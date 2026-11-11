from django.template.response import TemplateResponse
from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required


from backend.decorators import add_cycle_info, log_player_action, commandant_required
from backend.utils import request_params, get_language, commandant_owns_colony
from data.colonies import get_colonies_controlled_by_commandant, get_colony
from data.districts import get_district
from data.districts_types import get_district_type, get_all_buildable_districts_types
from data.buildings import districts_with_free_slots, get_district_buildings, relocation_cost
from data.buildings_types import buildings_catalogue, construction_trees, resources_text, upgrade_tree
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

    colonies = get_colonies_controlled_by_commandant(server, commandant['id'], add_coo_image=True)

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

    language = get_language(request)
    buildable_districts = get_all_buildable_districts_types(server, commandant, language)
    catalogue = buildings_catalogue(server, commandant, language)
    types = {building_type['internal_name']: building_type for building_type in catalogue}
    free_districts = districts_with_free_slots(server, commandant['colonies'], language)
    trees = {}  # By category of district

    def relocation_text(building_type, other_planet):
        cost = relocation_cost(building_type, other_planet)
        return resources_text({resource: dict(info, quantity=cost[resource]) for resource, info in building_type.get('costs', {}).items()})

    districts = []
    for district_id in colony_dict['districts']:
        district = get_district(server, district_id)  # Specific district info
        district.update(get_district_type(server, district['district_type']))  # Global district values
        district['id'] = str(district_id)
        district['name'] = localized_name(district, get_language(request))
        district['buildings'] = get_district_buildings(server, district_id, append_building_type=True)
        for building in district['buildings']:
            building['name'] = localized_name(building, language)
            building['type'] = types.get(building['building_type'])
            building['upgrade_tree'] = upgrade_tree(catalogue, building['building_type'], district['category'])
            building['relocation_targets'] = [dict(target, cost=relocation_text(building['type'] or {}, target['planet'] != colony_dict['coordinate']))
                                              for target in free_districts if str(target['id']) != district['id']
                                              and (building['building_type_data'] or {}).get(target['category'])]
        district['buildings_slots_free'] = district['buildings_slots_total'] - len(district['buildings'])
        district['free_districts_slots'] = district['districts_slots'] - len(colony_dict['districts']) + 1
        if district['category'] not in trees:
            trees[district['category']] = construction_trees(catalogue, district['category'])
        district['construction_trees'] = trees[district['category']]

        districts.append(district)



    return TemplateResponse(request, 'game/colony.html',
                            {'server': server, 'colony': colony_dict,
                             'districts': districts, 'filter_districts': filter_districts,
                             'buildable_districts': buildable_districts,
                             })


