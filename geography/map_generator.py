
import random

from data import map_generator
from geography import sector, solar, planet
from backend.utils import seed_convertor


def generate(p):

    if p['seed'][0] == '0':
        raise ValueError("The first digit of a seed can't be a 0")

    random.seed(int(p['seed']))

    # SEED USAGE
    # generator seed + sector x and y position + system x and y position + position in the solar system

    sectors = []
    for y in range(p['nb_sectors_axe_y']):
        sectors.append([])
        for x in range(p['nb_sectors_axe_x']):

            sector_seed = seed_convertor((p['seed'], 6), (y, 3), (x, 3))
            new_sector = sector.generate_sector(pos_y=y,
                                                pos_x=x,
                                                seed=sector_seed
                                                )
            sectors[y].append(new_sector)

    print(sectors)


def load_map_generator_excel(excel_map_generator_path, sheet_map_generator_name):

    import pylightxl as xl

    with open(excel_map_generator_path, 'rb') as f:
        xldb = xl.readxl(f, ws=sheet_map_generator_name)

        mg_config = []

        for col in xldb.ws(ws=sheet_map_generator_name).cols:

            if col[0] and not col[0][0] == '#':

                # Manual end of file
                if col[0] == 'END_OF_FILE':
                    break

                # Header
                if col[0] in ('Map Generator Properties', 'sector_type'):
                    titles = col
                    continue

                conf = {}
                for i in range(len(titles)):

                    if titles[i] in (None, '', 'END_OF_FILE', 'Map Generator Properties'):
                        continue

                    if col[i] == '':
                        conf[titles[i]] = None
                    elif col[i] in ('True', 'true'):
                        conf[titles[i]] = True
                    elif col[i] in ('False', 'false'):
                        conf[titles[i]] = False
                    else:
                        conf[titles[i]] = col[i]

                mg_config.append(conf)

    return mg_config


def generate_new_server_geography(server_name):
    # ##### Generation parameters ##### #

    TSS_config_excel_path = 'C:\\Users\\Benoit\\Desktop\\Thousand Suns Saga\\TSS.xlsx'

    # General map generator values
    # Even if you keep the default values, remember to change the random generator seed !
    map_generator_config = load_map_generator_excel(
        excel_map_generator_path=TSS_config_excel_path,
        sheet_map_generator_name='MapGenerator')

    # Sectors generator values
    mg_sector_config = load_map_generator_excel(
        excel_map_generator_path=TSS_config_excel_path,
        sheet_map_generator_name='MG_sectors')

    print(map_generator_config)
    print(mg_sector_config)
    # store the params into DB to be able to generate servers with different params all on the same webserver
    # as the thousands "uninteresting" solar systems aren't saved into DB but regenerated every time a player need it
    map_generator.set_map_generator_parameters(server_name, map_generator_config)
    map_generator.set_map_generator_parameters(server_name, mg_sector_config, mg_type='sector')

    #generate(generation_params)


if __name__ == '__main__':

    generate_new_server_geography('Alpha')