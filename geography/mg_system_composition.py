
import random
from math import sqrt

from backend import utils
from data import map_generator, sectors, systems
from backend.utils import seed_convertor, probability_picker


def random_pick_system_type(server, sector_type):
    systems_type_probabilities = {}
    mp_params_sector_type = map_generator.get_mp_params_sector_type(server, sector_type)


    print(mp_params_sector_type)
    for var, value in mp_params_sector_type.items():
        if 'solar_type_probability_' in var:
            var = var.replace('solar_type_probability_','')
            systems_type_probabilities[var] = value if value else 0

    print('PROB:', systems_type_probabilities)
    #utils.probability_picker()
    return None


def generate_system(server, seed, system_type=None):

    # SEED USAGE
    # generator seed + sector x and y position + system x and y position

    # Pick system type if not preselected
    #if not system_type:
    sector_type = sectors.get_sector_by_seed(server, seed[0:12])['sector_type']
    system_type = random_pick_system_type(server, sector_type)

    new_system = {
        "_id": seed,
        "system_type": system_type,
        "system_coordinates": [],
    }  # Some values like pos_y, pos_x, sector_seed will be auto-added when querying db

    print(new_system)