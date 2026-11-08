
from game.models import MapGeneratorParameter
from database.schemas import on_server


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


@on_server
def set_map_generator_parameters(server, map_generator_params, mg_type='global'):

    MapGeneratorParameter.objects.filter(mg_type=mg_type).delete()

    for param in map_generator_params:
        MapGeneratorParameter.objects.create(mg_type=mg_type, data=param)


@on_server
def get_map_generator_parameters(server, mg_type=None):

    if not mg_type or mg_type == 'global':
        return MapGeneratorParameter.objects.filter(mg_type='global').first().as_dict()
    return [param.as_dict() for param in MapGeneratorParameter.objects.filter(mg_type=mg_type).order_by('id')]

