
import sys
import random
from datetime import datetime

from django_tss.settings import DATABASES, mongodb_settings
from database import create_tables
from database.load_technologies import load_technologies
from database.load_resources import load_resources
from database.load_buildings import load_buildings
from database.db_connect import clients
from data import server_details, statistics, starting_values
from geography import map_generator, mg_sectors
from statistics import stats_geography


""" SERVER STATUS
open : users can create an account and play
close : users can play but not create new accounts
test : only superuser can create an account
stop : the server is fixed in time at the end of the game, no new account or any order
dead : everything shut down
"""

""" ADMIN ONLY VISIBILITY
The game server will be displayed on the public site  
"""


server_name = 'Alpha_Boardgame'
excel_server_params = 'TSS_boardgame.xlsx'

version = 0.1
gameplay = 'skirmish'  # 'saga' (main game) / 'skirmish' (boardgame)

language = 'international'  # 'fr' / 'en' / 'international'
roleplay = 'HRP'  # 'RP' / 'HRP'


admin_only_visibility = False
server_status = 'open'

hide_visualisation = True  # Map visualization at the end of the generation




# Manual addition in settings database declarations necessary
if server_name not in DATABASES:
    print("/!\\ Before creating a new server, please declare the following line in django_tss.settings.DATABASES :\n"
          "'"+server_name+"': mongodb_settings('"+server_name+"'),")
    sys.exit()


#
if server_details.get_server_details(server_name):

    # Test server, don't care about deleting it
    if server_name == 'Alpha_test':
        try:
            clients['TSS_' + server_name].drop_database('TSS_' + server_name)
        except KeyError:
            ...
        server_details.delete_server_details(server_name)

    else:
        print("/!\\ "+server_name+" already exist ! Do you want to remove the previous server ? (Y/n)")
        if input() in ('Y', 'y'):
            clients['TSS_' + server_name].drop_database('TSS_' + server_name)
            server_details.delete_server_details(server_name)
        else:
            print('Server creation canceled')
            sys.exit()


#db_connect(mongodb_settings('TSS_' + server_name))


# SERVER DETAILS

create_tables.create_server_database(server_name)
server_details.create_server(server_name, version, status=server_status, admin_only_visibility=admin_only_visibility,
                             language=language, roleplay=roleplay, gameplay=gameplay)


# TECHNOLOGIES
load_technologies(excel_tech_path=excel_server_params,
                  sheet_tech_name='Techs',
                  server_name=server_name,
                  delete_actual_techs=True)

# RESOURCES
load_resources(excel_tech_path=excel_server_params,
               sheet_resources_name='Resources',
               server_name=server_name,
               delete_actual_resources=True)

# BUILDINGS
load_buildings(excel_tech_path=excel_server_params,
               sheet_resources_name='Buildings',
               server_name=server_name,
               delete_actual_buildings=True)

# NEW PLAYERS STARTING VALUES
starting_values.create_starting_values(server_name)

# GEOGRAPHY

map_generator.remove_past_generation(server_name)

map_generator.load_map_generator_parameters(server_name, excel_server_params)

mg_sectors.generate_sectors(server_name, hide_visualisation)

# STATISTICS

systems_types_per_sector = stats_geography.statistics_systems_types_per_sector(server_name)
statistics.set_statistics_category(server_name, "mg_systems_types_per_sector", systems_types_per_sector)
print(systems_types_per_sector)

systems_types_global = stats_geography.statistics_systems_types_global(server_name)
statistics.set_statistics_category(server_name, "mg_systems_types_global", systems_types_global)
print(systems_types_global)


