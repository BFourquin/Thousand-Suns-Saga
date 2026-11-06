
from backend import utils
from game.models import Colony, to_id
from database.schemas import on_server
from data.districts import create_district, get_district
from data.districts_types import get_district_type
from data.admin import cheat_log



def additional_colony_info(colony, add_coo_image):
    # Add geographic_location and images

    colony['geographic_location'] = utils.info_from_seed(colony['coordinate'])
    if add_coo_image:
        colony['coordinate_image'] = 'images/placeholder/telluric.png'  # TODO get image from planet table

    return colony


@on_server
def get_colony(server, id, add_coo_image=False):
    colony = Colony.objects.get(id=to_id(id)).as_dict()
    return additional_colony_info(colony, add_coo_image)


@on_server
def get_colonies_controlled_by_commandant(server, commandant_id, add_coo_image=False):
    colonies = Colony.objects.filter(controller=commandant_id).order_by('id')
    return [additional_colony_info(colony.as_dict(), add_coo_image) for colony in colonies]


@on_server
def get_colonies_at_coordinates(server, coordinates_ids):
    return [colony.as_dict() for colony in Colony.objects.filter(coordinate__in=coordinates_ids)]


@on_server
def get_all_colonies(server):
    return [colony.as_dict() for colony in Colony.objects.all().order_by('id')]


@on_server
def update_colony(server, colony_id, param, value):
    Colony.objects.filter(id=colony_id).update(**{param: value})


@on_server
def new_colony(server, commandant_id, colony_name, coordinate, colony_type, central_district_type):

    colony = Colony.objects.create(
        name=colony_name,
        owner_id=commandant_id,
        controller_id=commandant_id,
        coordinate=coordinate,
        colony_type=colony_type,  # TODO more types
    )

    create_district(server, colony.id, central_district_type)


########################################################################################################################
# DISTRICTS SLOTS


@on_server
def recalculate_districts_slots(server, colony_id):
    colony = get_colony(server, colony_id)

    slots_total = 0
    slots_occupied = 0

    for district_id in colony['districts']:
        district = get_district(server, district_id)

        slots_total += get_district_type(server, district['district_type'])['districts_slots']
        if district['category'] != 'central_district':
            slots_occupied += 1  # TODO take into account future special districts with different slots size

    update_colony(server, colony_id, 'districts_slots_total', slots_total)
    update_colony(server, colony_id, 'districts_slots_occupied', slots_occupied)

    if colony['districts_slots_occupied'] > colony['districts_slots_total']:
        ...
        # TODO cheat log
        # cheat_log()

    return slots_total, slots_occupied
