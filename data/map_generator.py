
from backend.models import MapGeneratorParameter


def get_seed_type(seed):
    seed_types_by_length = {
        '4': 'server',
        '10': 'sector',
        '16': 'system',
        '18': 'coordinate'
    }
    if str(len(str(seed))) in seed_types_by_length.keys():
        return seed_types_by_length[str(len(str(seed)))]
    else:
        print(str(seed), seed, seed_types_by_length.keys())
        raise Exception(str(seed) + ' is not a recognized seed length')


def set_map_generator_parameters(server, map_generator_params, mg_type='global'):

    MapGeneratorParameter.objects.filter(server=server, mg_type=mg_type).delete()

    for param in map_generator_params:
        MapGeneratorParameter.objects.create(server_id=server, mg_type=mg_type, data=param)


def get_map_generator_parameters(server, mg_type=None):

    if not mg_type or mg_type == 'global':
        return MapGeneratorParameter.objects.filter(server=server, mg_type='global').first().as_dict()
    return [param.as_dict() for param in MapGeneratorParameter.objects.filter(server=server, mg_type=mg_type).order_by('id')]


def get_mg_params_sector_type(server, sector_type):
    return MapGeneratorParameter.objects.filter(server=server, mg_type='sectors', data__sector_type=sector_type).first().as_dict()


def get_mg_system_type(server, system_type):
    return MapGeneratorParameter.objects.filter(server=server, mg_type='systems_types', data__system_type=system_type).first().as_dict()


def get_mg_system_composition(server, solar_type):
    return MapGeneratorParameter.objects.filter(server=server, mg_type='systems_compositions', data__solar_type=solar_type).first().as_dict()
