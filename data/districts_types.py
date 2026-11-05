
from data.names import localized_name
from backend.models import DistrictType


def get_district_type(server, internal_name, language=None):

    district = DistrictType.objects.filter(server=server, internal_name=internal_name).first()
    if not district:
        return None

    district = district.as_dict()
    if language:
        district['name'] = localized_name(district, language)
    return district


def get_all_districts_types(server, language=None):
    districts = [district.as_dict() for district in DistrictType.objects.filter(server=server).order_by('id')]

    if language:
        for i in range(len(districts)):
            districts[i]['name'] = localized_name(districts[i], language)
    return districts


def get_all_buildable_districts_types(server, commandant, language=None):

    districts = get_all_districts_types(server)

    # Remove unconstructibles districts
    for district in districts[:]:  # Duplicate districts list to iterate correctly while removing entries
        if district['category'] == 'central_district':  # Central district are not buildable, only upgradable
            # TODO remove unbuildable districts limited by tech too
            districts.remove(district)

    # More info on resources cost and maintenance
    from data.resources import add_infos_to_resources_dict
    for i in range(len(districts)):
        districts[i]['build_cost'] = add_infos_to_resources_dict(server, districts[i]['build_cost'], commandant, language)
        districts[i]['maintenance'] = add_infos_to_resources_dict(server, districts[i]['maintenance'], commandant, language)

        # Check if any resource is missing to build it
        districts[i]['enough_stockpiles'] = True
        for resource_dict in districts[i]['build_cost'].values():
            if not resource_dict['enough_stockpiles']:
                districts[i]['enough_stockpiles'] = False
                break

    if language:
        for i in range(len(districts)):
            districts[i]['name'] = localized_name(districts[i], language)

    return districts
