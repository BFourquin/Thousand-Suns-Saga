
import os
import random
from datetime import datetime

from data import map_generator
from geography import mg_sectors, solar, planet
from statistics import stats_geography
from backend.utils import seed_convertor


def excel_importer(excel_map_generator_path, sheet_map_generator_name):

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
                if col[0] in ('Map Generator Properties', 'sector_type', 'system_type', 'solar_type'):
                    titles = col
                    continue

                conf = {}
                for i in range(len(titles)):

                    if titles[i] in (None, '', 'END_OF_FILE', 'Map Generator Properties') or titles[i][0] == '#':
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


def load_map_generator_parameters(server_name, excel_path):

    # General map generator values
    # Even if you keep the default values, remember to change the random generator seed !
    map_generator_config = excel_importer(
        excel_map_generator_path=excel_path,
        sheet_map_generator_name='MapGenerator')

    # Sectors generator values
    mg_sector_config = excel_importer(
        excel_map_generator_path=excel_path,
        sheet_map_generator_name='MG_sectors')

    # Systems types generator values
    mg_systems_types_config = excel_importer(
        excel_map_generator_path=excel_path,
        sheet_map_generator_name='MG_systems_types')

    # Systems compositions values
    mg_systems_config = excel_importer(
        excel_map_generator_path=excel_path,
        sheet_map_generator_name='MG_systems')

    # store the params into DB to be able to generate servers with different params all on the same webserver
    # as the thousands "uninteresting" solar systems aren't saved into DB but regenerated every time a player need it
    map_generator.set_map_generator_parameters(server_name, map_generator_config)
    map_generator.set_map_generator_parameters(server_name, mg_sector_config, mg_type='sectors')
    map_generator.set_map_generator_parameters(server_name, mg_systems_types_config, mg_type='systems_types')
    map_generator.set_map_generator_parameters(server_name, mg_systems_config, mg_type='systems_compositions')


def remove_past_generation(server):
    from database.db_connect import databases

    for category in ('sectors', 'systems', 'planets'):
        databases['TSS_' + server][category].delete_many({})


if __name__ == '__main__':

    project_path = os.path.dirname(__file__)
    excel_path = os.path.abspath(project_path + '/../../TSS.xlsx')
    server_name = 'Alpha'

    remove_past_generation(server_name)

    load_map_generator_parameters(server_name, excel_path)

    mg_sectors.generate_sectors(server_name)

    print(stats_geography.statistics_systems_types_per_sector(server_name))
    print(stats_geography.statistics_systems_types_global(server_name))



# Speed comparison between system generation and querying in DB

    from mg_system_composition import generate_system
    from data import systems

    start = datetime.now()
    generate_system(server_name, '1003000000094080')
    end = datetime.now()
    print(end-start)

    start = datetime.now()
    systems.get_system_by_seed(server_name, '1003000000094080')
    end = datetime.now()
    print(end-start)
