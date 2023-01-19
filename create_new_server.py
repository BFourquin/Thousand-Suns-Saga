
import os
import random
from datetime import datetime


from database.load_technologies import load_technologies
from geography import map_generator, mg_sectors, solar, planet
from statistics import stats_geography




server_name = 'Alpha'
excel_server_params = '..\\TSS.xlsx'


# TECHNOLOGIES

load_technologies(excel_tech_path=excel_server_params,
                  sheet_tech_name='Techs',

                  server_name=server_name,
                  delete_actual_techs=True)

# GEOGRAPHY

map_generator.remove_past_generation(server_name)

map_generator.load_map_generator_parameters(server_name, excel_server_params)

mg_sectors.generate_sectors(server_name)

print(stats_geography.statistics_systems_types_per_sector(server_name))
print(stats_geography.statistics_systems_types_global(server_name))

