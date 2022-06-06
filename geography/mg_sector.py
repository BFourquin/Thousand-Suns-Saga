
import random

from data import map_generator, sector
from backend.utils import seed_convertor, probability_picker


def generate_sector_basic_values(pos_y, pos_x, seed):

    new_sector = {
        "pos_y": pos_y,
        "pos_x": pos_x,
        "seed": seed,
        "sector_type": None
    }

    return new_sector


def generate_sectors(server):

    # Server generation parameters
    mg_params = map_generator.get_map_generator_parameters(server, mg_type='global')
    mg_sector_params = map_generator.get_map_generator_parameters(server, mg_type='sector')

    if str(mg_params['seed'])[0] == '0':
        raise ValueError("The first digit of a seed can't be a 0")
    random.seed(int(mg_params['seed']))

    # SEED USAGE
    # generator seed + sector x and y position + system x and y position + position in the solar system

    # TODO REMOVE, testing only
    from database.db_connect import clients
    clients['TSS_'+server]['sector'].remove({})
    # REMOVE

    ####################################################################################################################
    # First pass : attribute sectors default values

    for y in range(mg_params['nb_sectors_axe_y']):
        for x in range(mg_params['nb_sectors_axe_x']):
            sector_seed = seed_convertor((mg_params['seed'], 6), (y, 3), (x, 3))
            new_sector = generate_sector_basic_values(pos_y=y, pos_x=x, seed=sector_seed)
            sector.create_sector(server, new_sector)

    ####################################################################################################################
    # Second pass : borders and corners sectors

    if mg_params['force_empty_border_sectors']:
        for y in range(mg_params['nb_sectors_axe_y']):
            for x in range(mg_params['nb_sectors_axe_x']):

                if (y == 0 or y == mg_params['nb_sectors_axe_y']-1) or \
                   (x == 0 or x == mg_params['nb_sectors_axe_x']-1):

                    corner_coordinates = ((0, 0),
                                          (0, mg_params['nb_sectors_axe_x']-1),
                                          (mg_params['nb_sectors_axe_y']-1, 0),
                                          (mg_params['nb_sectors_axe_y']-1, mg_params['nb_sectors_axe_x']-1))
                    sector_type = 'corner' if (y, x) in corner_coordinates else 'border'

                    border_sector = sector.get_sector(server, y, x)
                    border_sector['sector_type'] = sector_type
                    sector.create_sector(server, border_sector)

    ####################################################################################################################
    # Third pass : native sectors

    native_sectors_to_place = mg_params['forced_native_sectors']
    tested_coordinates = []

    while native_sectors_to_place:

        # Position
        y, x = random.randint(0, mg_params['nb_sectors_axe_y']-1), random.randint(0, mg_params['nb_sectors_axe_x']-1)

        # Check if position already picked previously
        if (y, x) in tested_coordinates:
            if len(tested_coordinates) == mg_params['nb_sectors_axe_y']*mg_params['nb_sectors_axe_x']:
                raise ValueError("You can't place that much native sectors considering the map size and placement "
                                 "restrictions \n[ " + str(mg_params['forced_native_sectors'])+ ' native sectors / ' +
                                 str(mg_params['nb_sectors_axe_y']*mg_params['nb_sectors_axe_x']) + ' sectors' +
                                 ' (generations rules :' +
                                 (' "prevent_natives_sectors_on_borders"' if mg_params['prevent_natives_sectors_on_borders'] else '') +
                                 (' "prevent_natives_sectors_direct_neighbors"' if mg_params['prevent_natives_sectors_direct_neighbors'] else '') +
                                 (' "prevent_natives_sectors_diagonal_neighbors"' if mg_params['prevent_natives_sectors_diagonal_neighbors'] else '') + ')')
            continue
        else:
            tested_coordinates.append((y, x))

        selected_sector = sector.get_sector(server, y, x)

        # Rules of placement (border of the map, adjacency to another native sector)

        if selected_sector['sector_type'] in ('border', 'corner') and mg_params['prevent_natives_sectors_on_borders']:
            continue

        invalid_placement = False

        if mg_params['prevent_natives_sectors_direct_neighbors']:
            for neighbour_sector in sector.get_direct_neighbours_sectors(server, y, x):
                if neighbour_sector['sector_type'] == 'native':
                    invalid_placement = True
                    break

        if mg_params['prevent_natives_sectors_diagonal_neighbors']:
            for neighbour_sector in sector.get_diagonal_neighbours_sectors(server, y, x):
                if neighbour_sector['sector_type'] == 'native':
                    invalid_placement = True
                    break

        if not invalid_placement:
            selected_sector['sector_type'] = 'native'
            sector.create_sector(server, selected_sector)
            native_sectors_to_place -= 1

    ####################################################################################################################
    # Fourth pass : random sectors types

    sector_type_probabilities = {}
    for s in mg_sector_params:
        sector_type_probabilities[s['sector_type']] = s['probabilities']

    for y in range(mg_params['nb_sectors_axe_y']):
        for x in range(mg_params['nb_sectors_axe_x']):

            selected_sector = sector.get_sector(server, y, x)

            if selected_sector['sector_type'] is None:

                sector_type = probability_picker(sector_type_probabilities, random.random())

                selected_sector['sector_type'] = sector_type
                sector.create_sector(server, selected_sector)

    ####################################################################################################################
    # Fourth pass : attribute sector values

    total_players_possible = 0
    total_systems = 0

    for y in range(mg_params['nb_sectors_axe_y']):
        for x in range(mg_params['nb_sectors_axe_x']):

            selected_sector = sector.get_sector(server, y, x)
            for sector_type_params in mg_sector_params:
                if sector_type_params['sector_type'] == selected_sector['sector_type']:
                    params = sector_type_params
                    break

            selected_sector['nb_systems'] = random.randint(params['min_systems'], params['max_systems'])
            selected_sector['nb_natives_start'] = random.randint(params['min_natives_start'], params['max_natives_start'])
            sector.create_sector(server, selected_sector)

            total_systems += selected_sector['nb_systems']
            total_players_possible += selected_sector['nb_natives_start']

    print('TOTAL PLAYER STARTING POSITIONS :', total_players_possible)
    print('TOTAL SOLAR SYSTEMS :', total_systems)

    ####################################################################################################################
    # Visualisation

    for y in range(mg_params['nb_sectors_axe_y']):
        for x in range(mg_params['nb_sectors_axe_x']):
            print(str(sector.get_sector(server, y, x)['sector_type'])[:6], ' '*(6-len(str(sector.get_sector(server, y, x)['sector_type']))), end=' | ')
        print()

