
import os
import sys

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_tss.settings')
django.setup()

from django.db import transaction

from database.schemas import server_schema
from database.load_technologies import load_technologies
from database.load_resources import load_resources
from database.load_buildings import load_buildings
from data import server_details, statistics, starting_values, cycles
from geography import map_generator, mg_sectors
from stats import stats_geography


""" SERVER STATUS
open : users can create an account and play
close : users can play but not create new accounts
test : only superuser can create an account
stop : the server is fixed in time at the end of the game, no new account or any order
dead : everything shut down, its players can still look at what was
"""

""" ADMIN ONLY VISIBILITY
The game server will be displayed on the public site  
"""


server_name = 'Alpha_Boardgame'
excel_server_params = 'TSS_boardgame.xlsx'

version = 0.1
gameplay = 'skirmish'  # 'saga' (main game) / 'skirmish' (boardgame)

roleplay = 'HRP'  # 'RP' / 'HRP'
language = 'international'  # 'fr' / 'en' / 'international'
timezone = 'Europe/Paris'
exclusive = False  # True for a serious server asking a lot of time : a player can only be on one exclusive server


admin_only_visibility = False
server_status = 'open'

hide_visualisation = True  # Map visualization at the end of the generation




if server_details.get_server_details(server_name):

    # Test server, don't care about deleting it
    if server_name == 'Alpha_test':
        server_details.delete_server_details(server_name)

    else:
        print("/!\\ "+server_name+" already exist ! Do you want to remove the previous server ? (Y/n)")
        if input() in ('Y', 'y'):
            server_details.delete_server_details(server_name)
        else:
            print('Server creation canceled')
            sys.exit()


# SERVER DETAILS

server_details.create_server(server_name, version, status=server_status, admin_only_visibility=admin_only_visibility,
                             language=language, roleplay=roleplay, gameplay=gameplay, timezone_name=timezone, exclusive=exclusive)


# TECHNOLOGIES
load_technologies(server_name,
                  excel_tech_path=excel_server_params,
                  sheet_tech_name='Techs',
                  delete_actual_techs=True)

# RESOURCES
load_resources(server_name,
               excel_tech_path=excel_server_params,
               sheet_resources_name='Resources',
               delete_actual_resources=True)

# BUILDINGS
load_buildings(server_name,
               excel_tech_path=excel_server_params,
               sheet_resources_name='Buildings',
               delete_actual_buildings=True)

# NEW PLAYERS STARTING VALUES
starting_values.create_starting_values(server_name)

# GEOGRAPHY

map_generator.remove_past_generation(server_name)

map_generator.load_map_generator_parameters(server_name, excel_server_params)

with transaction.atomic(), server_schema(server_name):  # A single commit instead of one per row : much faster, and no half generated map
    mg_sectors.generate_sectors(server_name, hide_visualisation)

# STATISTICS

systems_types_per_sector = stats_geography.statistics_systems_types_per_sector(server_name)
statistics.set_statistics_category(server_name, "mg_systems_types_per_sector", systems_types_per_sector)
print(systems_types_per_sector)

systems_types_global = stats_geography.statistics_systems_types_global(server_name)
statistics.set_statistics_category(server_name, "mg_systems_types_global", systems_types_global)
print(systems_types_global)

# OTHERS

cycles.create_cycle_entry(server_name)

