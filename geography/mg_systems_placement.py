
import random
from math import sqrt

from backend import utils
from data import map_generator, sectors, systems
from geography import mg_system_composition
from backend.utils import seed_convertor, probability_picker


def generate_system_coordinates(sector, used_coordinates, mg_params):

    while True:  # Continue until a valid coordinate is found

        # Position
        x, y = random.randint(0, 99), random.randint(0, 99)

        # Check if position already picked previously
        if (y, x) in used_coordinates:
            continue

        # ###################################################################
        # Rules of placement (border of the map, clusters and centered voids)
        if sector['sector_type'] == 'border' or 'corner':
            if sector['pos_y'] == 0:
                if y < random.randint(0, 99) + 10:
                    continue
            if sector['pos_x'] == 0:
                if x < random.randint(0, 99) + 10:
                    continue
            if sector['pos_y'] == mg_params['nb_sectors_axe_y'] - 1:
                if y > random.randint(0, 99) - 10:
                    continue
            if sector['pos_x'] == mg_params['nb_sectors_axe_y'] - 1:
                if x > random.randint(0, 99) - 10:
                    continue

        distance_from_center = sqrt((x - 50) ** 2 + (y - 50) ** 2)

        if sector['sector_type'] in ('empty', 'void_centered'):
            if distance_from_center < random.randint(0, 99) + 10:
                continue

        if sector['sector_type'] == 'cluster':
            if 25 < distance_from_center + random.randint(-15, 15) < 50:
                continue

        return y, x


def generate_sector_systems(server, sector):

    # Server generation parameters
    mg_params = map_generator.get_map_generator_parameters(server, mg_type='global')
    mg_sector_params = map_generator.get_mg_params_sector_type(server, sector_type=sector['sector_type'])

    # Random seed from sector
    random.seed(int(sector['seed']))

    print('Generating systems for sector ', sector['pos_y'], '_', sector['pos_x'], sep='')

    ####################################################################################################################
    # First pass : systems coordinates

    systems_coordinates = []
    for _ in range(sector['nb_systems']):

        y, x = generate_system_coordinates(sector, systems_coordinates, mg_params)
        systems_coordinates.append((y, x))

    sector['systems_coordinates'] = systems_coordinates
    sectors.set_sector(server, sector)

    ####################################################################################################################
    # Second pass : forced system placement

    systems_placed = {}  # {system_seed: system_type} Will only contain the systems generated into DB

    systems_types_to_place = {
        'native': sector['nb_natives_start']
    }

    # While there is systems to place
    while sum(systems_types_to_place.values()):
        y, x = systems_coordinates[random.randint(0, len(systems_coordinates))]

        # SEED USAGE
        # generator seed + sector y and x position + system y and x position
        system_seed = seed_convertor((sector['seed'], 10), (y, 3), (x, 3))

        # Do not write over already generated system
        if system_seed in systems_placed.keys():
            continue

        # Select a system type that still need to be placed
        for system_type, remaining_to_place in systems_types_to_place.items():
            if not remaining_to_place:
                continue

            #  print(y, x, system_type)
            new_system = mg_system_composition.generate_system(server, system_seed, system_type)
            systems.set_system(server, new_system)

            systems_placed[system_seed] = system_type
            systems_types_to_place[system_type] -= 1
            break

    ####################################################################################################################
    # Generate all the remaining, random systems

    for y, x in systems_coordinates:

        # SEED USAGE
        # generator seed + sector y and x position + system y and x position
        system_seed = seed_convertor((sector['seed'], 10), (y, 3), (x, 3))

        # Do not write over already generated system
        if system_seed not in systems_placed.keys():

            new_system = mg_system_composition.generate_system(server, system_seed)
            systems.set_system(server, new_system)

