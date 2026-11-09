import math
from collections import defaultdict
from random import randint

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from backend.models import CommandantAccount, FINISHED_SERVER_STATUSES, Server, UserExtended
from game.models import Commandant, Cycle, System, to_id
from database.schemas import on_server
from data.errors import GameError
from data import ententes, starting_values as sv
from data.user import get_user_by_name
from actions import colonize
from backend import utils


def check_account_rules(server, user_id):
    # One commandant per server, and one exclusive server at a time. Dead commandants and finished servers don't count.

    # Locked until the end of the transaction : two simultaneous creations on two servers can't both pass
    User.objects.select_for_update().get(id=user_id)

    accounts = CommandantAccount.objects.filter(user_id=user_id, status='active')
    if accounts.filter(server=server).exists():
        raise GameError(_("Vous avez déjà un commandant sur ce serveur"))
    if Server.objects.get(pk=server).exclusive and \
            accounts.filter(server__exclusive=True).exclude(server__status__in=FINISHED_SERVER_STATUSES).exists():
        raise GameError(_("Ce serveur est exclusif et vous jouez déjà sur un autre serveur exclusif"))


def pick_home(available):
    # The cradle the most settled first, and in it the free home the farthest from the players already there : nobody alone
    # in an empty cradle, nobody at the door of another. A map without zones (the old generator) : at random.
    free = {str(seed)[:16]: seed for seed in available}
    taken, free_in = defaultdict(list), defaultdict(list)
    for seed, region in System.objects.filter(system_type='native').values_list('seed', 'region'):
        if region is not None:
            (free_in if seed in free else taken)[region].append(seed)
    if not free_in:
        return available[randint(0, len(available) - 1)]
    region = max(free_in, key=lambda r: (len(taken[r]), -r))

    def place(seed):
        return int(seed[4:7]) * 100 + int(seed[10:13]), int(seed[7:10]) * 100 + int(seed[13:16])

    if not taken[region]:
        return free[free_in[region][randint(0, len(free_in[region]) - 1)]]
    return free[max(free_in[region], key=lambda seed: min(math.dist(place(seed), place(other)) for other in taken[region]))]


@on_server
@transaction.atomic
def create_commandant(server, user, commandant_name, civilisation_name):

    user = get_user_by_name(user)
    check_account_rules(server, user['id'])

    # Locked until the end of the transaction : two new players can't take the same planet
    starting_values = sv.get_starting_values(server, lock=True)

    if not starting_values['available_native_planets']:
        raise GameError(_("Ce serveur ne possède plus de places disponibles"))

    starting_planet_id = pick_home(starting_values['available_native_planets'])

    try:
        commandant = Commandant.objects.create(

            # Account parameters
            commandant_name=commandant_name,
            civilisation_name=civilisation_name,
            gender='m',  # TODO gender

            portrait='images/commandants/default_portrait.jpg',
            flag='images/commandants/default_flag.jpg',

            status='active',
            user_id=user['id'],
            creation_date=timezone.now(),

            # Starting position
            native_sector=utils.info_from_seed(starting_planet_id)['sector_id'],
            native_system=utils.info_from_seed(starting_planet_id)['system_id'],
            native_planet=starting_planet_id,

            # Empire and allegiances
            resources=starting_values['starting_resources'],
            technologies=starting_values['starting_technologies'],
            player_modifiers=starting_values['starting_modifiers'],
        )
        CommandantAccount.objects.create(server_id=server, commandant_id=commandant.id, user_id=user['id'],
                                         commandant_name=commandant_name)
    except IntegrityError:  # A simultaneous creation took the name after the check of the view
        raise GameError(_("Ce nom de commandant est déjà pris"))

    ententes.join_native_entente(server, commandant)

    # The lists of a cycle are only filled when it starts, and the first one starts before any player
    current_cycle = Cycle.objects.order_by('-cycle_nb').first()
    if current_cycle:
        current_cycle.commandants_cycle_playing.add(commandant)

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
    return CommandantAccount.objects.filter(commandant_name__iexact=name).exists()


@on_server
def civilisation_name_taken(server, name):
    # Case insensitive, on this server only
    return Commandant.objects.filter(civilisation_name__iexact=name).exists()


@on_server
def get_commandant(server, id):
    commandant = Commandant.objects.filter(id=to_id(id)).first()
    return commandant.as_dict() if commandant else None


@on_server
def get_commandants(server, ids):
    return [commandant.as_dict() for commandant in Commandant.objects.filter(id__in=ids)]


@on_server
def get_commandant_names(server):
    return list(Commandant.objects.order_by('commandant_name').values_list('commandant_name', flat=True))


@on_server
def update_commandant(server, commandant_id, param, value):
    Commandant.objects.filter(id=commandant_id).update(**{param: value})


@on_server
@transaction.atomic
def delete_commandant(server, commandant_id):
    # /!\ TEST AND ADMIN ACTION ONLY (removal of the commandant and of everything belonging to it)
    # Use commandant_death() instead for normal endgame or death of a player
    Commandant.objects.filter(id=commandant_id).delete()
    CommandantAccount.objects.filter(server=server, commandant_id=commandant_id).delete()
    UserExtended.objects.filter(playing_on_server=server, playing_on_commandant=commandant_id).update(
        playing_on_server=None, playing_on_commandant=None)


########################################################################################################################
# THE PLACES OF THE MAPS : the last ones a commandant looked at and his favourites, see game.models.Commandant

RECENT_PLACES = 10
FAVOURITE_PLACES = 50  # shortcut: beyond, a new favourite is refused instead of being paginated ; raise it if players ask


def _same_place(one, other):
    return (one['kind'], one['id']) == (other['kind'], other['id'])


@on_server
@transaction.atomic
def remember_place(server, commandant_id, place):
    # The latest first, each place once
    commandant = Commandant.objects.select_for_update().only('recent_places').get(id=commandant_id)
    commandant.recent_places = [place, *(known for known in commandant.recent_places if not _same_place(known, place))][:RECENT_PLACES]
    commandant.save(update_fields=['recent_places'])


@on_server
@transaction.atomic
def toggle_favourite_place(server, commandant_id, place):
    # Added at the end, or removed if it already is a favourite. False if the list is full.
    commandant = Commandant.objects.select_for_update().only('favourite_places').get(id=commandant_id)
    kept = [known for known in commandant.favourite_places if not _same_place(known, place)]
    if len(kept) == len(commandant.favourite_places):
        if len(kept) >= FAVOURITE_PLACES:
            return False
        kept.append(place)
    commandant.favourite_places = kept
    commandant.save(update_fields=['favourite_places'])
    return True
