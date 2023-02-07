
import sys
import random
from datetime import datetime

from django_tss.settings import DATABASES
from database import create_tables
from database.load_technologies import load_technologies
from database.db_connect import clients
from data import server_details, statistics
from geography import map_generator, mg_sectors
from statistics import stats_geography



server_name = 'Alpha2'
excel_server_params = '..\\TSS.xlsx'

server_status = 'test'
admin_only_visibility = True


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


# Manual addition in settings database declarations necessary
if server_name not in DATABASES:
    print("/!\\ Before creating a new server, please declare the following line in django_tss.settings.DATABASES :\n"
          "'"+server_name+"': mongodb_settings('"+server_name+"'),")
    sys.exit()


#
if server_details.get_server_details(server_name):
    print("/!\\ "+server_name+" already exist ! Do you want to remove the previous server ? (Y/n)")
    if input() in ('Y', 'y'):
        clients['TSS_' + server_name].drop_database('TSS_' + server_name)
        server_details.delete_server_details(server_name)
    else:
        print('Server creation canceled')
        sys.exit()



# SERVER DETAILS

create_tables.create_server_database('TSS_' + server_name)
server_details.create_server(server_name, status=server_status, admin_only_visibility=admin_only_visibility)


# TECHNOLOGIES

load_technologies(excel_tech_path=excel_server_params,
                  sheet_tech_name='Techs',

                  server_name=server_name,
                  delete_actual_techs=True)

# GEOGRAPHY

map_generator.remove_past_generation(server_name)

map_generator.load_map_generator_parameters(server_name, excel_server_params)

mg_sectors.generate_sectors(server_name)

# STATISTICS

systems_types_per_sector = stats_geography.statistics_systems_types_per_sector(server_name)
statistics.set_statistics_category(server_name, "mg_systems_types_per_sector", systems_types_per_sector)
print(systems_types_per_sector)

systems_types_global = stats_geography.statistics_systems_types_global(server_name)
statistics.set_statistics_category(server_name, "mg_systems_types_global", systems_types_global)
print(systems_types_global)


