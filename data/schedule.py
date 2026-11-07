"""
The steps of the game played at the local hours of each server (columns hour_* of backend_server, from its Excel).
The system scheduler runs the command run_schedule every 5 minutes, the hours are read again at each run.

- A step only runs in the LATE_TOLERANCE after its hour. Later, after a breakdown, it is skipped : never two cycles
  or rounds in a row when the server comes back. An admin can still pass a cycle by hand.
- A step that fails, or never ends, blocks every other step of its server until an admin unblocks it : nothing is
  played on a game left in an unknown state. The anticheat is apart (anticheat.rules), it never blocks anything.
"""

import logging
from datetime import timedelta

from dateutil import tz
from django.db import IntegrityError, transaction
from django.utils import timezone

from backend.models import FINISHED_SERVER_STATUSES, ScheduledRun, Server
from data import cycles


logger = logging.getLogger(__name__)

LATE_TOLERANCE = timedelta(minutes=15)  # Three runs of the system scheduler
FIRST_CYCLE_DELAY = timedelta(hours=24)  # With delay_first_cycle : the first players don't get a cycle of a few hours
MIN_CYCLE_DURATION = timedelta(hours=12)  # A cycle passed by hand just before its hour isn't followed by another one


def end_cycle_step(server, due):
    cycle = cycles.get_current_cycle(server)
    if cycle['datetime_start'] > due - MIN_CYCLE_DURATION:
        return 'Cycle ' + str(cycle['cycle_nb']) + ' commencé moins de ' + str(MIN_CYCLE_DURATION) + ' avant : déjà passé à la main'
    cycles.end_cycle(server, cycle['cycle_nb'])


# (step, column of its hour, function(server, due) returning why it was skipped, or None), in the order of the day.
# The combat rounds will come before the cycle, with their columns hour_*_combat_round, once written.
STEPS = (('end_cycle', 'hour_cycle', end_cycle_step),)


def last_due(hour, server_tz, now):
    # The last time the clock of the server showed this hour. fold=0 : the hour seen twice at the end of the summer time is played once.
    local_now = now.astimezone(server_tz)
    due = local_now.replace(hour=hour, minute=0, second=0, microsecond=0, fold=0)
    if due > local_now:
        due -= timedelta(days=1)
    return tz.resolve_imaginary(due)  # The hour skipped by the start of the summer time is played just after


def blocking_run(server):
    return ScheduledRun.objects.filter(server=server, status__in=ScheduledRun.BLOCKING_STATUSES).order_by('due').first()


def run_due_steps(now=None):
    now = now or timezone.now()
    played = []

    # Everything is manual on a skirmish server, and nothing is played once the game is over
    for server in Server.objects.exclude(status__in=FINISHED_SERVER_STATUSES).exclude(gameplay='skirmish').order_by('server_name'):
        if blocking_run(server):
            continue

        first_due = server.opening_date + (FIRST_CYCLE_DELAY if server.delay_first_cycle else timedelta(0))
        for step, hour_column, function in STEPS:
            hour = getattr(server, hour_column)
            if hour is None:
                continue
            due = last_due(hour, tz.gettz(server.timezone), now)
            if not timedelta(0) <= now - due <= LATE_TOLERANCE or due < first_due:
                continue

            try:
                with transaction.atomic():  # Committed before the step : a run killed in the middle stays 'running', so blocking
                    run = ScheduledRun.objects.create(server=server, step=step, due=due, started_at=now, status='running')
            except IntegrityError:
                continue  # Already played, by this run of the system scheduler or another

            try:
                note = function(server.server_name, due)
            except Exception as error:
                logger.exception('Schedule : %s failed on %s, the server is blocked', step, server.server_name)
                ScheduledRun.objects.filter(pk=run.pk).update(status='failed', note=f'{type(error).__name__} : {error}', finished_at=timezone.now())
                break

            ScheduledRun.objects.filter(pk=run.pk).update(status='skipped' if note else 'done', note=note or '', finished_at=timezone.now())
            played.append(f'{server.server_name} : {step}' + (' (skipped)' if note else ''))

    return played


def unblock(server, username):
    # The blocking step isn't played again : the admin passes it by hand if needed
    ScheduledRun.objects.filter(server=server, status__in=ScheduledRun.BLOCKING_STATUSES).update(status='abandoned', handled_by=username)


def schedule_state(server):
    # For the admins : what blocks the server, otherwise the last step played
    return {'blocking': blocking_run(server['server_name']),
            'last': ScheduledRun.objects.filter(server=server['server_name']).order_by('-due', '-started_at').first(),
            'manual': server['gameplay'] == 'skirmish'}
