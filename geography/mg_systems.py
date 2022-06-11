
import random
from math import sqrt

from data import map_generator, sectors
from backend.utils import seed_convertor, probability_picker


def generate_system_basic_values(pos_y, pos_x, sector_id, seed):

    new_system = {
        "_id": seed,
        "pos_y": pos_y,
        "pos_x": pos_x,
        "seed": seed,
        "sector_id": sector_id,
        "system_type": None,
    }
    return new_system


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


def generate_systems(server, sector):

    # Server generation parameters
    mg_params = map_generator.get_map_generator_parameters(server, mg_type='global')
    for s in map_generator.get_map_generator_parameters(server, mg_type='sectors'):
        if s['sector_type'] == sector['sector_type']:
            mg_sector_params = s
            break

    # Random seed from sector
    random.seed(int(sector['seed']))

    print('Generating systems for sector ', sector['pos_y'], '_', sector['pos_x'], sep='')

    ####################################################################################################################
    # First pass : systems coordinates

    used_coordinates = []
    for _ in range(sector['nb_systems']//2):  # TODO remove the division

        y, x = generate_system_coordinates(sector, used_coordinates, mg_params)
        used_coordinates.append((y, x))

    sector['systems_coordinates'] = used_coordinates
    sectors.set_sector(server, sector)

    ####################################################################################################################
    # Second pass : forced system placement

    native_systems = random.randint(mg_sector_params['min_natives_start'], mg_sector_params['max_natives_start'])

    while native_systems:
        y, x = used_coordinates[random.randint(0, len(used_coordinates))]

        # TODO test is already generated

        position = str(y) + '_' + str(x)

        # SEED USAGE
        # generator seed + sector y and x position + system y and x position
        system_seed = seed_convertor((sector['seed'], 12), (y, 3), (x, 3))

        generate_system_basic_values(y, x, sector['_id'], system_seed)

        native_systems -= 1
