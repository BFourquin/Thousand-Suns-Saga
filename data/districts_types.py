
from data.names import localized_name
from game.models import DistrictType
from database.schemas import on_server
from data.technology import within_tech_level


def is_buildable_district(district_type):
    # A central district only comes with its colony : it takes no slot and gives some
    return district_type['category'] != 'central_district' and within_tech_level(district_type)


@on_server
def get_district_type(server, internal_name, language=None):

    district = DistrictType.objects.filter(internal_name=internal_name).first()
    if not district:
        return None

    district = district.as_dict()
    if language:
        district['name'] = localized_name(district, language)
    return district


@on_server
def get_all_districts_types(server, language=None):
    districts = [district.as_dict() for district in DistrictType.objects.all().order_by('id')]

    if language:
        for i in range(len(districts)):
            districts[i]['name'] = localized_name(districts[i], language)
    return districts


@on_server
def get_all_buildable_districts_types(server, commandant, language=None):

    districts = [district for district in get_all_districts_types(server) if is_buildable_district(district)]

    # More info on resources cost and maintenance
    from data.resources import add_infos_to_resources_dict, get_resources_by_name
    resources = get_resources_by_name(server)
    for i in range(len(districts)):
        districts[i]['build_cost'] = add_infos_to_resources_dict(resources, districts[i]['build_cost'], commandant, language)
        districts[i]['maintenance'] = add_infos_to_resources_dict(resources, districts[i]['maintenance'], commandant, language)

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
