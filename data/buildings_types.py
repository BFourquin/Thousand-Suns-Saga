
from data.names import localized_name
from game.models import BuildingType
from database.schemas import on_server


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
    # TODO /!\ copier coller des districts à vérifier !!!

    buildings = get_all_buildings_types(server)

    # Remove unconstructibles buildings
    for building in buildings[:]:  # Duplicate buildings list to iterate correctly while removing entries
        if building['category'] == 'central_building':  # Central building are not buildable, only upgradable
            # TODO remove unbuildable buildings limited by tech too
            buildings.remove(building)

    # More info on resources cost and maintenance
    from data.resources import add_infos_to_resources_dict
    for i in range(len(buildings)):
        buildings[i]['build_cost'] = add_infos_to_resources_dict(server, buildings[i]['build_cost'], commandant, language)
        buildings[i]['maintenance'] = add_infos_to_resources_dict(server, buildings[i]['maintenance'], commandant, language)

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
