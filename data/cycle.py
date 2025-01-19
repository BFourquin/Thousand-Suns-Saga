
import datetime
from random import randint
from bson.objectid import ObjectId

from database.db_connect import databases
from data import server_details
from data.commandant import get_commandant_by_object_id
from data.resources import get_all_resources_parameters, resource_change, check_enough_resource
from data.user import get_user_by_name, update_user, pull_param_user
from backend import utils


def end_cycle(server_name):

    server = server_details.get_server_details(server_name)


    # Production > Consommation > Vente > Achat > Bilan économique > Bilan ressources


    for commandant_id in server['active_commandants']:
        commandant = get_commandant_by_object_id(server_name, commandant_id)
        print(commandant['commandant_name'])

        ################################################################################################################
        # RESOURCES PRODUCTION

        for resource in get_all_resources_parameters(server_name):
            if resource['internal_name'] in commandant['resources'].keys():

                resource_change(server_name, commandant_id, resource['internal_name'], +5)  # TODO quantity






if __name__ == '__main__':
    end_cycle('Alpha_test')


