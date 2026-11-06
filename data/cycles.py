from django.db import transaction
from django.utils import timezone

from game.models import Commandant, Cycle, to_id
from database.schemas import on_server
from data.server_details import get_tz
from data.commandant import update_commandant
from data.economy import apply_cycle_economy
from data.modifiers import tick_modifiers


@on_server
def create_cycle_entry(server_name, last_cycle=None):

    cycle = Cycle.objects.create(cycle_nb=last_cycle['cycle_nb']+1 if last_cycle else 1,
                                 datetime_start=timezone.now())

    # Boardgame version : manual passing of cycles
    for commandant_id in active_commandants(server_name).values_list('id', flat=True):
        if last_cycle and commandant_id in last_cycle['commandants_cycle_absent']:
            cycle.commandants_cycle_absent.add(commandant_id)
            cycle.commandants_cycle_finished.add(commandant_id)
        else:
            cycle.commandants_cycle_playing.add(commandant_id)


@on_server
def active_commandants(server_name):
    return Commandant.objects.filter(status='active')


@on_server
def current_cycle_row(server_name):
    return Cycle.objects.all().order_by('-cycle_nb').first()


@on_server
def get_current_cycle(server_name):
    cycle = current_cycle_row(server_name)
    return cycle.as_dict() if cycle else None


@on_server
def update_cycle(server, param, value):
    Cycle.objects.filter(id=current_cycle_row(server).id).update(**{param: value})


@on_server
def push_param_cycle(server, param, value):
    getattr(current_cycle_row(server), param).add(value)


@on_server
def pull_param_cycle(server, param, value):
    getattr(current_cycle_row(server), param).remove(value)


########################################################################################################################
# Boardgame version : manual passing of cycles

@on_server
def mark_commandant_cycle_finished(server, commandant_id):
    commandant_id = to_id(commandant_id)
    pull_param_cycle(server, 'commandants_cycle_playing', commandant_id)
    if not commandant_id in get_current_cycle(server)['commandants_cycle_finished']:
        push_param_cycle(server, 'commandants_cycle_finished', commandant_id)
        update_commandant(server, commandant_id, 'time_cycle_finished', timezone.now())

@on_server
def mark_commandant_cycle_playing(server, commandant_id):
    commandant_id = to_id(commandant_id)
    if not commandant_id in get_current_cycle(server)['commandants_cycle_absent']:
        pull_param_cycle(server, 'commandants_cycle_finished', commandant_id)
        if not commandant_id in get_current_cycle(server)['commandants_cycle_playing']:
            push_param_cycle(server, 'commandants_cycle_playing', commandant_id)
            update_commandant(server, commandant_id, 'time_cycle_finished', None)

# Player declared absent : always display as cycle finished

@on_server
def mark_commandant_cycle_absent(server, commandant_id):
    commandant_id = to_id(commandant_id)
    pull_param_cycle(server, 'commandants_cycle_playing', commandant_id)
    if not commandant_id in get_current_cycle(server)['commandants_cycle_finished']:
        push_param_cycle(server, 'commandants_cycle_finished', commandant_id)
    if not commandant_id in get_current_cycle(server)['commandants_cycle_absent']:
        push_param_cycle(server, 'commandants_cycle_absent', commandant_id)
        update_commandant(server, commandant_id, 'time_cycle_finished', None)

@on_server
def mark_commandant_cycle_present(server, commandant_id):
    commandant_id = to_id(commandant_id)
    pull_param_cycle(server, 'commandants_cycle_finished', commandant_id)
    pull_param_cycle(server, 'commandants_cycle_absent', commandant_id)
    if not commandant_id in get_current_cycle(server)['commandants_cycle_playing']:
        push_param_cycle(server, 'commandants_cycle_playing', commandant_id)
        update_commandant(server, commandant_id, 'time_cycle_finished', timezone.now())


########################################################################################################################


@on_server
@transaction.atomic
def end_cycle(server_name):

    Cycle.objects.filter(datetime_end=None).update(datetime_end=timezone.now())
    create_cycle_entry(server_name, last_cycle=get_current_cycle(server_name))

    # Reset commandants' cycle status
    active_commandants(server_name).update(time_cycle_finished=None)

    apply_cycle_economy(server_name)
    tick_modifiers(server_name)
