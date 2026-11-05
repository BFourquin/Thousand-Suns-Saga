
from django.db import transaction

from backend.models import Building, Colony, District, to_id
from data import colonies, districts_types, buildings


def get_district(server, id):
    district = District.objects.filter(colony__owner__server=server, id=to_id(id)).first()
    return district.as_dict() if district else None


def get_all_districts(server):
    return [district.as_dict() for district in District.objects.filter(colony__owner__server=server).order_by('id')]


def update_district(server, district_id, param, value):
    District.objects.filter(colony__owner__server=server, id=district_id).update(**{param: value})


########################################################################################################################


@transaction.atomic
def create_district(server, colony_id, district_type):
    # Return False if the colony has no free slot for it

    district_type_properties = districts_types.get_district_type(server, district_type)

    # Locked until the end of the transaction : two simultaneous builds can't take the same slot
    colony = Colony.objects.select_for_update(of=('self',)).get(owner__server=server, id=colony_id)

    # The central district doesn't use a slot, hence the + 1
    # TODO take into account future special districts with different slots size
    if district_type_properties['category'] != 'central_district' \
            and colony.districts.count() >= colony.districts_slots_total + 1:
        return False

    District.objects.create(
        colony=colony,
        district_type=district_type,
        category=district_type_properties['category'],
        buildings_slots_free=district_type_properties['buildings_slots'],
        buildings_slots_total=district_type_properties['buildings_slots'],
        population=district_type_properties['build_population'],
        hp=district_type_properties['hp'],
        hp_max=district_type_properties['hp'],
    )

    # Central district : they define how many districts slots you have
    colonies.recalculate_districts_slots(server, colony_id)
    return True


@transaction.atomic
def delete_district(server, commandant_id, district_id, refund_ratio=0.75):
    from data.resources import add_resources  # Placed here to prevent circular import

    # Locked until deleted : spamming the request can't refund the same district twice
    district = District.objects.select_for_update(of=('self',)).filter(colony__owner__server=server, id=to_id(district_id)).first()
    if not district:
        return False

    # TODO check if destruction is valid

    colony_id, district_type = district.colony_id, district.district_type
    district.delete()
    colonies.recalculate_districts_slots(server, colony_id)

    # TODO refund of the district's buildings, once constructing them has a cost

    # District cost refund
    build_cost = districts_types.get_district_type(server, district_type)['build_cost']
    add_resources(server, commandant_id,
                  {resource: int(quantity * refund_ratio) for resource, quantity in build_cost.items()})
    return True


def recalculate_buildings_slots(server, district_id):
    district = get_district(server, district_id)

    slots_total = districts_types.get_district_type(server, district['district_type'])['districts_slots']
    slots_occupied = Building.objects.filter(home_district=district_id).count()


    # TODO take into account future special buildings with different slots size
    """
    for building_id in district['buildings']:
        building = buildings.get_building(server, building_id)

        slots_total += buildings.get_building_type(server, building['building_type'])['buildings_slots']
        if building['category'] != 'central_building':
            slots_occupied += 1

    update_district(server, district_id, 'buildings_slots_total', slots_total)
    update_district(server, district_id, 'buildings_slots_occupied', slots_occupied)
    """

    # TODO cheat log
    if slots_occupied > slots_total:
        ...
        # cheat_log()

    return slots_total, slots_occupied
