
from game.models import Building, BuildingType, to_id
from database.schemas import on_server
from data import colonies, buildings_types, districts


@on_server
def get_building(server, id):
    building = Building.objects.filter(id=to_id(id)).first()
    return building.as_dict() if building else None


@on_server
def get_district_buildings(server, district_id, append_building_type=False):

    buildings = [building.as_dict() for building in Building.objects.filter(home_district=district_id).order_by('id')]

    if append_building_type:
        types = BuildingType.objects.filter(internal_name__in={b['building_type'] for b in buildings})
        types = {building_type.internal_name: building_type.as_dict() for building_type in types}
        for building in buildings:
            building['building_type_data'] = types.get(building['building_type'])

    return buildings


@on_server
def update_building(server, building_id, param, value):
    Building.objects.filter(id=building_id).update(**{param: value})


########################################################################################################################


@on_server
def construct_building(server, district_id, building_type):

    home_district = districts.get_district(server, district_id)
    building_type_properties = buildings_types.get_building_type(server, building_type)

    # Check if slot available for a new building
    if home_district['buildings_slots_free'] < 1:
        return False
    # Resources
    # TODO

    Building.objects.create(
        name_fr=building_type_properties['name_fr'],
        name_en=building_type_properties['name_en'],
        building_type=building_type,
        home_district_id=district_id,
    )
    districts.recalculate_buildings_slots(server, district_id)


@on_server
def delete_building(server, building_id, refund_ratio=0.75):

    building = get_building(server, building_id)
    if not building:
        return False


    # TODO check if destruction is valid

    Building.objects.filter(id=building_id).delete()


    # RESOURCES REFUNDING (done after to prevent multiple refunding by spamming faster than DB deletion)
    resources_refund = {}

    # Building cost refund
    building_type = buildings_types.get_building_type(server, building['building_type'])
    for resource, quantity in building_type['build_cost']:
        if resource in resources_refund:
            resources_refund[resource] += quantity * refund_ratio
        else:
            resources_refund[resource] = quantity * refund_ratio
            # TODO refund on destruction


@on_server
def set_activation_percent_building(server, building_id, activation_percent):

    if activation_percent < 0:
        activation_percent = 0
    if activation_percent > 100:
        activation_percent = 100

    update_building(server, building_id, 'activation_percent', activation_percent)
