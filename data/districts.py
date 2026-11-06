
from django.db import transaction

from game.models import Colony, District, to_id
from database.schemas import on_server
from data import colonies, districts_types, buildings


@on_server
def get_district(server, id):
    district = District.objects.filter(id=to_id(id)).first()
    return district.as_dict() if district else None


@on_server
def get_all_districts(server):
    return [district.as_dict() for district in District.objects.all().order_by('id')]


@on_server
def update_district(server, district_id, param, value):
    District.objects.filter(id=district_id).update(**{param: value})


########################################################################################################################


@on_server
@transaction.atomic
def create_district(server, colony_id, district_type):
    # Return False if the colony has no free slot for it

    district_type_properties = districts_types.get_district_type(server, district_type)

    # Locked until the end of the transaction : two simultaneous builds can't take the same slot
    colony = Colony.objects.select_for_update().get(id=colony_id)

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


@on_server
@transaction.atomic
def delete_district(server, commandant_id, district_id, refund_ratio=0.75):
    from data.resources import add_resources  # Placed here to prevent circular import

    # Locked until deleted : spamming the request can't refund the same district twice
    district = District.objects.select_for_update().filter(id=to_id(district_id)).first()
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
