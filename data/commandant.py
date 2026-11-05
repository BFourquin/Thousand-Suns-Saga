from random import randint

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from backend.models import Commandant, to_id
from data.errors import GameError
from data import starting_values as sv
from data.user import get_user_by_name
from actions import colonize
from backend import utils


@transaction.atomic
def create_commandant(server, user, commandant_name, civilisation_name):

    user = get_user_by_name(user)

    # Locked until the end of the transaction : two new players can't take the same planet
    starting_values = sv.get_starting_values(server, lock=True)

    if not starting_values['available_native_planets']:
        raise GameError(_("Ce serveur ne possède plus de places disponibles"))

    starting_planet_id = starting_values['available_native_planets'][randint(0, len(starting_values['available_native_planets'])-1)]

    try:
        commandant = Commandant.objects.create(

            # Account parameters
            commandant_name=commandant_name,
            civilisation_name=civilisation_name,
            gender='m',  # TODO gender

            portrait='images/commandants/default_flag.jpg',
            flag='images/commandants/default_portrait.jpg',

            server_id=server,
            status='active',
            user_id=user['id'],
            creation_date=timezone.now(),

            # Starting position
            native_entente=None,  # TODO native_faction
            native_sector=utils.info_from_seed(starting_planet_id)['sector_id'],
            native_system=utils.info_from_seed(starting_planet_id)['system_id'],
            native_planet=starting_planet_id,

            # Empire and allegiances
            resources=starting_values['starting_resources'],
            technologies=starting_values['starting_technologies'],
            player_modifiers=starting_values['starting_modifiers'],
        )
    except IntegrityError:  # A simultaneous creation took the name after the check of the view
        raise GameError(_("Ce nom de commandant est déjà pris"))

    # Starting colony
    colonize.colonize(server, commandant.id,
                      fleet_id=None,
                      coordinate_seed=starting_planet_id,
                      colony_name=None,
                      colony_type='starting_colony',
                      central_district_type='district_territory',
                      admin_force_action=True)

    # Welcome and tutorial report
    from data.report import create_report  # Placed here to prevent circular import
    create_report(server, commandant.id, 'welcome_on_TSS')


def commandant_name_taken(name):
    # Case insensitive, on every server
    return Commandant.objects.filter(commandant_name__iexact=name).exists()


def civilisation_name_taken(server, name):
    # Case insensitive, on this server only
    return Commandant.objects.filter(server=server, civilisation_name__iexact=name).exists()


def get_commandant(server, id):
    commandant = Commandant.objects.filter(server=server, id=to_id(id)).first()
    return commandant.as_dict() if commandant else None


def get_commandants(server, ids):
    return [commandant.as_dict() for commandant in Commandant.objects.filter(server=server, id__in=ids)]


def get_commandant_by_name(server, name):
    commandant = Commandant.objects.filter(server=server, commandant_name=name).first()
    return commandant.as_dict() if commandant else None


def get_commandant_from_any_server(id):
    commandant = Commandant.objects.filter(id=id).first()
    return commandant.as_dict() if commandant else None


def update_commandant(server, commandant_id, param, value):
    Commandant.objects.filter(server=server, id=commandant_id).update(**{param: value})


def delete_commandant(server, commandant_id):
    # /!\ TEST AND ADMIN ACTION ONLY (removal of the commandant and of everything belonging to it)
    # Use commandant_death() instead for normal endgame or death of a player
    Commandant.objects.filter(server=server, id=commandant_id).delete()
