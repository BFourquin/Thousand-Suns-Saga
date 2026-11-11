
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
from geography import galaxy, map_generator
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


server_name = 'TSS_Pre_Alpha'
excel_server_params = 'TSS_a_trier.xlsx'

# The sheets of the Excel, in their order : a requisite comes before what needs it, the added resources after the others
tech_sheets = ('Techs_retro', 'Techs_new')
resource_sheets = ('Resources', 'Resources_new')
buildings_sheet = 'Buildings_new'
max_players = 200  # None : the row max_players of the sheet MapGenerator

version = 0.1

roleplay = 'HRP'  # 'RP' / 'HRP'
language = 'international'  # 'fr' / 'en' / 'international'
timezone = 'Europe/Paris'
exclusive = False  # True for a serious server asking a lot of time : a player can only be on one exclusive server


admin_only_visibility = True
server_status = 'test'





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
                             language=language, roleplay=roleplay, timezone_name=timezone, exclusive=exclusive)

server_details.set_server_config(server_name, map_generator.excel_importer(excel_server_params, 'Config')[0])


# TECHNOLOGIES
for i, sheet in enumerate(tech_sheets):
    load_technologies(server_name,
                      excel_tech_path=excel_server_params,
                      sheet_tech_name=sheet,
                      delete_actual_techs=i == 0)

# RESOURCES
for i, sheet in enumerate(resource_sheets):
    load_resources(server_name,
                   excel_tech_path=excel_server_params,
                   sheet_resources_name=sheet,
                   delete_actual_resources=i == 0)

# BUILDINGS
load_buildings(server_name,
               excel_tech_path=excel_server_params,
               sheet_resources_name=buildings_sheet,
               delete_actual_buildings=True)

# NEW PLAYERS STARTING VALUES
starting_values.create_starting_values(server_name)

# GEOGRAPHY

map_generator.remove_past_generation(server_name)

map_generator.load_map_generator_parameters(server_name, excel_server_params)

with transaction.atomic(), server_schema(server_name):  # A single commit instead of one per row : much faster, and no half generated map
    drawn = map_generator.generate_map(server_name, excel_server_params, max_players)
map_generator.save_blank_map(server_name, drawn)
print(galaxy.report(drawn))  # The pictures of a map : the page admin_map_trial, with the same seed

# STATISTICS

systems_types_per_sector = stats_geography.statistics_systems_types_per_sector(server_name)
statistics.set_statistics_category(server_name, "mg_systems_types_per_sector", systems_types_per_sector)
print(systems_types_per_sector)

systems_types_global = stats_geography.statistics_systems_types_global(server_name)
statistics.set_statistics_category(server_name, "mg_systems_types_global", systems_types_global)
print(systems_types_global)

# OTHERS

cycles.create_cycle_entry(server_name)

