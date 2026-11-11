import math

from django.db import transaction
from django.db.models import Count

from game.models import Building, BuildingType, District, DistrictType, to_id
from database.schemas import on_server
from data import colonies, buildings_types, districts
from data.names import localized_name


# Moving a building to another district costs this part of its construction, more to another planet
RELOCATION_COST_RATIO = 0.5
RELOCATION_TO_ANOTHER_PLANET_COST_RATIO = 0.8


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


def _count_free_slots(district):
    district.buildings_slots_free = district.buildings_slots_total - district.buildings.count()
    district.save(update_fields=['buildings_slots_free'])


@on_server
@transaction.atomic
def destroy_building(server, commandant_id, building_id, refund_ratio=0.75):
    from data.resources import add_resources  # Placed here to prevent circular import

    # Locked until deleted : spamming the request can't refund the same building twice
    building = Building.objects.select_for_update().filter(id=to_id(building_id)).first()
    if not building:
        return False

    district, building_type = building.home_district, building.building_type
    building.delete()
    _count_free_slots(district)

    build_cost = (buildings_types.get_building_type(server, building_type) or {}).get('build_cost') or {}
    add_resources(server, commandant_id, {resource: int(quantity * refund_ratio) for resource, quantity in build_cost.items()})
    return True


@on_server
def upgrade_building(server, building_id, building_type):
    properties = buildings_types.get_building_type(server, building_type)
    Building.objects.filter(id=to_id(building_id)).update(building_type=building_type, name_fr=properties.get('name_fr'),
                                                        name_en=properties.get('name_en'))


@on_server
@transaction.atomic
def relocate_building(server, building_id, district_id):
    # Return False if the district has no free slot for it

    # Locked until the end of the transaction : two simultaneous moves can't take the same slot
    target = District.objects.select_for_update().get(id=to_id(district_id))
    if target.buildings_slots_total - target.buildings.count() < 1:
        return False

    building = Building.objects.select_for_update().get(id=to_id(building_id))
    origin = building.home_district
    building.home_district = target
    building.save(update_fields=['home_district'])
    _count_free_slots(origin)
    _count_free_slots(target)
    return True


def relocation_cost(building_type, other_planet):
    ratio = RELOCATION_TO_ANOTHER_PLANET_COST_RATIO if other_planet else RELOCATION_COST_RATIO
    return {resource: math.ceil(quantity * ratio) for resource, quantity in (building_type.get('build_cost') or {}).items()}


@on_server
def districts_with_free_slots(server, colonies_ids, language):
    # Where a building can be moved : the districts of these colonies with a free slot
    names = {district_type.internal_name: localized_name(district_type.as_dict(), language) for district_type in DistrictType.objects.all()}
    districts = District.objects.filter(colony_id__in=colonies_ids).select_related('colony').annotate(built=Count('buildings')).order_by('colony_id', 'id')
    return [{'id': district.id, 'category': district.category, 'colony': district.colony_id, 'colony_name': district.colony.name,
             'planet': district.colony.coordinate,
             'name': names.get(district.district_type, district.district_type), 'free': district.buildings_slots_total - district.built}
            for district in districts if district.buildings_slots_total > district.built]


@on_server
def set_activation_percent_building(server, building_id, activation_percent):

    if activation_percent < 0:
        activation_percent = 0
    if activation_percent > 100:
        activation_percent = 100

    update_building(server, building_id, 'activation_percent', activation_percent)
