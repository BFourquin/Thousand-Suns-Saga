
from django.db import transaction

from game.models import Building, BuildingType, District, to_id
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
@transaction.atomic
def construct_building(server, district_id, building_type):
    # Return False if the district has no free slot for it

    building_type_properties = buildings_types.get_building_type(server, building_type)

    # Locked until the end of the transaction : two simultaneous builds can't take the same slot
    home_district = District.objects.select_for_update().get(id=district_id)
    slots_free = home_district.buildings_slots_total - home_district.buildings.count()  # The stored value of old districts is wrong
    if slots_free < 1:
        return False

    Building.objects.create(
        name_fr=building_type_properties['name_fr'],
        name_en=building_type_properties['name_en'],
        building_type=building_type,
        home_district=home_district,
    )
    home_district.buildings_slots_free = slots_free - 1
    home_district.save(update_fields=['buildings_slots_free'])
    return True


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
