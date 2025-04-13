from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from bson.objectid import ObjectId


from database.db_connect import databases
from backend.utils import request_params, get_active_server_and_commandant_from_request
from backend.api_ui_interactions import api_pop_up, api_pop_up_and_redirect
from data.resources import check_enough_resources_dict
from data.colonies import check_available_district_slot, recalculate_districts_slots
from data.districts import create_district, delete_district



@login_required(login_url='/player_login/')
def api_build_district(request):

    params = request_params(request)
    server, commandant = get_active_server_and_commandant_from_request(request)

    if not server or not commandant:
        return redirect('/user_account/')
    if 'colony_id' not in params or ObjectId(params['colony_id']) not in commandant['colonies']:
        return redirect('/colonies/')

    # Get district type

    if 'district_type' not in params:
        return api_pop_up({"title": "Construction spécifiée incorrecte", "level": "danger"}, status=400)

    db = databases['TSS_' + server]['districts_types']
    district_type = db.find_one({'internal_name': params['district_type']})

    if not district_type:
        return api_pop_up({"title": "Construction spécifiée incorrecte", "level": "danger"}, status=400)


    # Check enough resources

    enough_resources, missing_resources = check_enough_resources_dict(server, commandant['_id'], district_type['build_cost'], return_missing_details=True)
    if not enough_resources:
        missing_details = ''
        for resource_name, quantity in missing_resources.items():
            missing_details += '\n' + resource_name + ' ' + str(quantity)  # TODO Resource name localization
        return api_pop_up({"title": "Ressources manquantes pour la construction", "level": "danger", "body": missing_details}, status=400)


    # Check building slot

    if not check_available_district_slot(server, params['colony_id'], 1):  # TODO take into account future special districts with different slots size
        return api_pop_up({"title": "Cette colonie n'a plus d'espace pour un nouveau district de cette taille", "level": "danger"}, status=400)


    # Check needed technologies unlocked
    # TODO buildings locked by tech

    create_district(server, params['colony_id'], district_type['internal_name'])
    return api_pop_up_and_redirect({"title": "District en construction", "level": "success"}, status=302, redirect='/colony/?colony_id='+str(params['colony_id']))



@login_required(login_url='/player_login/')
def api_delete_district(request):

    params = request_params(request)
    server, commandant = get_active_server_and_commandant_from_request(request)

    print(params)

    if not server or not commandant:
        return redirect('/user_account/')
    if 'colony_id' not in params or ObjectId(params['colony_id']) not in commandant['colonies']:
        return redirect('/colonies/')
    if 'district_id' not in params:
        return api_pop_up({"title": "Cible de la démolition invalide", "level": "danger"}, status=400)

    db = databases['TSS_' + server]['districts']
    district = db.find_one({"_id": ObjectId(params['district_id'])})

    if not district:
        return api_pop_up({"title": "Cible de la démolition invalide", "level": "danger"}, status=400)

    if district['category'] == 'central_district':
        return api_pop_up({"title": "Impossible de détruire la capitale de votre colonie sans l'abandonner", "level": "danger"}, status=400)

    # Anti-cheat
    if ObjectId(district['colony_id']) != ObjectId(params['colony_id']):
        ...  # TODO incoherent district and colony ids, possible tentative of destroying other player district
        return api_pop_up({"title": "Cible de la démolition invalide", "level": "danger"}, status=400)


    delete_district(server, params['colony_id'], ObjectId(params['colony_id']))
    return api_pop_up_and_redirect({"title": "Destruction en cours du district", "level": "success"}, status=302, redirect='/colony/?colony_id='+str(params['colony_id']))