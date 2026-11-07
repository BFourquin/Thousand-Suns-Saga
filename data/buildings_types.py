
from data.names import localized_name
from game.models import BuildingType
from database.schemas import on_server
from data.technology import within_tech_level


# shortcut: the column production_quantity of the Excel is still empty, each building gives this until it is filled
DEFAULT_PRODUCTION_QUANTITY = 1


def production_of(building_type):
    # What the building gives per cycle, working at full capacity
    resource = building_type.get('production')
    return {resource: building_type.get('production_quantity') or DEFAULT_PRODUCTION_QUANTITY} if resource else {}


def is_buildable(building_type, district_category):
    # The Excel has one column of booleans per category of district
    return bool(building_type.get(district_category)) and within_tech_level(building_type)


@on_server
def get_building_type(server, internal_name, language=None):

    building = BuildingType.objects.filter(internal_name=internal_name).first()
    if not building:
        return None

    building = building.as_dict()
    if language:
        building['name'] = localized_name(building, language)
    return building


@on_server
def get_all_buildings_types(server, language=None):
    buildings = [building.as_dict() for building in BuildingType.objects.all().order_by('id')]

    if language:
        for i in range(len(buildings)):
            buildings[i]['name'] = localized_name(buildings[i], language)
    return buildings


@on_server
def get_all_buildable_buildings_types(server, commandant, language=None):
    buildings = get_all_buildings_types(server)

    # Remove unconstructibles buildings
    for building in buildings[:]:  # Duplicate buildings list to iterate correctly while removing entries
        if building['category'] == 'central_building':  # Central building are not buildable, only upgradable
            # TODO remove unbuildable buildings limited by tech too
            buildings.remove(building)

    # More info on resources cost and maintenance
    from data.resources import add_infos_to_resources_dict, get_resources_by_name
    resources = get_resources_by_name(server)
    for i in range(len(buildings)):
        buildings[i]['build_cost'] = add_infos_to_resources_dict(resources, buildings[i]['build_cost'], commandant, language)
        buildings[i]['maintenance'] = add_infos_to_resources_dict(resources, buildings[i]['maintenance'], commandant, language)
        production = {resource: quantity for resource, quantity in production_of(buildings[i]).items() if resource in resources}
        production = add_infos_to_resources_dict(resources, production, commandant, language)
        buildings[i]['resources_columns'] = (production, buildings[i]['build_cost'], buildings[i]['maintenance'])

        # Check if any resource is missing to build it
        buildings[i]['enough_stockpiles'] = True
        for resource_dict in buildings[i]['build_cost'].values():
            if not resource_dict['enough_stockpiles']:
                buildings[i]['enough_stockpiles'] = False
                break

    if language:
        for i in range(len(buildings)):
            buildings[i]['name'] = localized_name(buildings[i], language)

    return buildings
