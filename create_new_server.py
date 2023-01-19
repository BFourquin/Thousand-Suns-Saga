
import os
import random
from datetime import datetime


from database.load_technologies import load_technologies
from data import server_details
from geography import map_generator, mg_sectors
from statistics import stats_geography



server_name = 'Alpha'
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


# SERVER DETAILS

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

print(stats_geography.statistics_systems_types_per_sector(server_name))
print(stats_geography.statistics_systems_types_global(server_name))

