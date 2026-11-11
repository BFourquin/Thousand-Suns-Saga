from functools import wraps

from django.db import transaction
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST


from backend.utils import request_params, get_active_server_and_commandant_from_request, commandant_owns_colony, get_language
from backend.api_ui_interactions import api_pop_up, api_pop_up_and_redirect, api_login_required, api_orders_open
from backend.decorators import log_player_action
from data.resources import check_enough_resources_dict, pay_resources
from data.colonies import get_colony
from data.districts import create_district, delete_district, get_district
from data.districts_types import get_district_type, is_buildable_district
from data.buildings import construct_building, destroy_building, get_building, get_district_buildings, relocate_building, \
    relocation_cost, set_activation_percent_building, upgrade_building
from data.buildings_types import buildings_catalogue, get_building_type, is_buildable, upgrade_tree
from game.models import to_id



def no_active_commandant():
    return api_pop_up_and_redirect({"title": _("Aucun commandant actif"), "level": "warning"}, status=400, redirect='/user_account/')


def invalid_colony():
    return api_pop_up_and_redirect({"title": _("Colonie invalide"), "level": "danger"}, status=400, redirect='/colonies/')



@require_POST
@api_login_required
@log_player_action
@api_orders_open
def api_build_district(request):

    params = request_params(request)
    server, commandant = get_active_server_and_commandant_from_request(request)

    if not server or not commandant:
        return no_active_commandant()
    if not commandant_owns_colony(commandant, params.get('colony_id')):
        return invalid_colony()

    # Get district type

    if 'district_type' not in params:
        return api_pop_up({"title": _("Construction spécifiée incorrecte"), "level": "danger"}, status=400)

    district_type = get_district_type(server, params['district_type'])

    if not district_type or not is_buildable_district(district_type):
        return api_pop_up({"title": _("Construction spécifiée incorrecte"), "level": "danger"}, status=400)


    # Check enough resources

    enough_resources, missing_resources = check_enough_resources_dict(server, commandant['id'], district_type['build_cost'], return_missing_details=True)
    if not enough_resources:
        missing_details = ''
        for resource_name, quantity in missing_resources.items():
            missing_details += '\n' + resource_name + ' ' + str(quantity)  # TODO Resource name localization
        return api_pop_up({"title": _("Ressources manquantes pour la construction"), "level": "danger", "body": missing_details}, status=400)


    # Check needed technologies unlocked
    # TODO buildings locked by tech

    with transaction.atomic():  # No free slot or any error : the payment is cancelled with the rest

        if not pay_resources(server, commandant['id'], district_type['build_cost']):
            return api_pop_up({"title": _("Ressources manquantes pour la construction"), "level": "danger"}, status=400)

        if not create_district(server, params['colony_id'], district_type['internal_name']):
            transaction.set_rollback(True)
            return api_pop_up({"title": _("Cette colonie n'a plus d'espace pour un nouveau district de cette taille"), "level": "danger"}, status=400)

    return api_pop_up_and_redirect({"title": _("District en construction"), "level": "success"}, status=200, redirect='/colony/?colony_id='+str(params['colony_id']))



@require_POST
@api_login_required
@log_player_action
@api_orders_open
def api_build_building(request):

    params = request_params(request)
    server, commandant = get_active_server_and_commandant_from_request(request)

    if not server or not commandant:
        return no_active_commandant()
    if not commandant_owns_colony(commandant, params.get('colony_id')):
        return invalid_colony()

    district = get_district(server, params.get('district_id'))
    building_type = get_building_type(server, params.get('building_type'))

    if not district or to_id(params['colony_id']) != district['colony'] \
            or not building_type or not is_buildable(building_type, district['category']):
        return api_pop_up({"title": _("Construction spécifiée incorrecte"), "level": "danger"}, status=400)

    with transaction.atomic():  # No free slot or any error : the payment is cancelled with the rest

        if not pay_resources(server, commandant['id'], building_type['build_cost']):
            return api_pop_up({"title": _("Ressources manquantes pour la construction"), "level": "danger"}, status=400)

        if not construct_building(server, district['id'], building_type['internal_name']):
            transaction.set_rollback(True)
            return api_pop_up({"title": _("Ce district n'a plus de place libre"), "level": "danger"}, status=400)

    return api_pop_up_and_redirect({"title": _("Bâtiment en construction"), "level": "success"}, status=200, redirect='/colony/?colony_id='+str(params['colony_id']))



@require_POST
@api_login_required
@log_player_action
@api_orders_open
def api_district_set_activation_percent(request):

    params = request_params(request)
    server, commandant = get_active_server_and_commandant_from_request(request)

    activation_percent = params['activation_percent']
    try:
        activation_percent = int(activation_percent)
    except ValueError:
        return api_pop_up({"title": _("Paramètre invalide"), "level": "danger"}, status=400)


    if not server or not commandant:
        return no_active_commandant()
    if not commandant_owns_colony(commandant, params.get('colony_id')):
        return invalid_colony()
    if 'district_id' not in params:
        return api_pop_up({"title": _("Cible de l'action invalide"), "level": "danger"}, status=400)


    district = get_district(server, params['district_id'])

    if not district:
        return api_pop_up({"title": _("Cible de l'action invalide"), "level": "danger"}, status=400)

    # Anti-cheat
    if str(district['colony']) != params['colony_id']:
        ...  # TODO incoherent district and colony ids, possible tentative of destroying other player district
        return api_pop_up({"title": _("Cible de l'action invalide"), "level": "danger"}, status=400)
    if not 0 <= activation_percent <= 100:
        ...  # TODO form manipulation cheat
        return api_pop_up({"title": _("Paramètre invalide"), "body": activation_percent, "level": "danger"}, status=400)

    for building in get_district_buildings(server, district['id']):
        set_activation_percent_building(server, building['id'], activation_percent)
    return api_pop_up_and_redirect({"title": _("Application du taux d'activation"), "level": "success"}, status=200, redirect='/colony/?colony_id='+str(params['colony_id']))


@require_POST
@api_login_required
@log_player_action
@api_orders_open
def api_delete_district(request):

    params = request_params(request)
    server, commandant = get_active_server_and_commandant_from_request(request)

    if not server or not commandant:
        return no_active_commandant()
    if not commandant_owns_colony(commandant, params.get('colony_id')):
        return invalid_colony()
    if 'district_id' not in params:
        return api_pop_up({"title": _("Cible de la démolition invalide"), "level": "danger"}, status=400)

    district = get_district(server, params['district_id'])

    if not district:
        return api_pop_up({"title": _("Cible de la démolition invalide"), "level": "danger"}, status=400)

    if district['category'] == 'central_district':
        return api_pop_up({"title": _("Impossible de détruire la capitale de votre colonie sans l'abandonner"), "level": "danger"}, status=400)

    # Anti-cheat
    if str(district['colony']) != params['colony_id']:
        ...  # TODO incoherent district and colony ids, possible tentative of destroying other player district
        return api_pop_up({"title": _("Cible de la démolition invalide"), "level": "danger"}, status=400)

    # TODO if recycling, long order instead of instantaneous
    delete_district(server, commandant['id'], params['district_id'])
    return api_pop_up_and_redirect({"title": _("Destruction en cours du district"), "level": "success"}, status=200, redirect='/colony/?colony_id='+str(params['colony_id']))


########################################################################################################################
# ORDERS ON A BUILDING : from its modal on the colony page


def building_order(view):
    # The building building_id must stand in the colony colony_id of the active commandant
    @require_POST
    @api_login_required
    @log_player_action
    @api_orders_open
    @wraps(view)
    def wrapper(request):
        params = request_params(request)
        server, commandant = get_active_server_and_commandant_from_request(request)

        if not server or not commandant:
            return no_active_commandant()
        if not commandant_owns_colony(commandant, params.get('colony_id')):
            return invalid_colony()

        building = get_building(server, params.get('building_id'))
        district = get_district(server, building['home_district']) if building else None
        if not district or district['colony'] != to_id(params['colony_id']):
            return api_pop_up({"title": _("Cible de l'action invalide"), "level": "danger"}, status=400)
        return view(request, params, server, commandant, building, district)
    return wrapper


def back_to_colony(title, params):
    return api_pop_up_and_redirect({"title": title, "level": "success"}, status=200, redirect='/colony/?colony_id=' + str(params['colony_id']))


@building_order
def api_building_set_activation_percent(request, params, server, commandant, building, district):
    activation_percent = to_id(params.get('activation_percent'))
    if activation_percent is None or activation_percent > 100:
        return api_pop_up({"title": _("Paramètre invalide"), "level": "danger"}, status=400)

    set_activation_percent_building(server, building['id'], activation_percent)
    return back_to_colony(_("Application du taux d'activation"), params)


@building_order
def api_upgrade_building(request, params, server, commandant, building, district):
    # Exactly what the tree of its modal offers
    tree = upgrade_tree(buildings_catalogue(server, commandant, get_language(request)), building['building_type'], district['category'])
    target = next((node for section in (tree or {}).get('sections', ()) for node in section['buildings']
                   if node['internal_name'] == params.get('building_type') and node['selectable']), None)
    if not target:
        return api_pop_up({"title": _("Amélioration impossible"), "level": "danger"}, status=400)

    with transaction.atomic():
        if not pay_resources(server, commandant['id'], target.get('build_cost') or {}):
            return api_pop_up({"title": _("Ressources manquantes pour la construction"), "level": "danger"}, status=400)
        upgrade_building(server, building['id'], target['internal_name'])

    return back_to_colony(_("Bâtiment amélioré"), params)


@building_order
def api_destroy_building(request, params, server, commandant, building, district):
    destroy_building(server, commandant['id'], building['id'])
    return back_to_colony(_("Bâtiment détruit"), params)


@building_order
def api_relocate_building(request, params, server, commandant, building, district):
    target = get_district(server, params.get('district_id'))
    building_type = get_building_type(server, building['building_type'])

    if not target or target['id'] == district['id'] or not commandant_owns_colony(commandant, target['colony']) \
            or not building_type or not building_type.get(target['category']):
        return api_pop_up({"title": _("Ce district ne peut pas accueillir ce bâtiment"), "level": "danger"}, status=400)

    with transaction.atomic():  # No free slot : the payment is cancelled with the rest
        other_planet = get_colony(server, target['colony'])['coordinate'] != get_colony(server, district['colony'])['coordinate']
        if not pay_resources(server, commandant['id'], relocation_cost(building_type, other_planet)):
            return api_pop_up({"title": _("Ressources manquantes pour la délocalisation"), "level": "danger"}, status=400)
        if not relocate_building(server, building['id'], target['id']):
            transaction.set_rollback(True)
            return api_pop_up({"title": _("Ce district n'a plus de place libre"), "level": "danger"}, status=400)

    return back_to_colony(_("Bâtiment délocalisé"), params)
