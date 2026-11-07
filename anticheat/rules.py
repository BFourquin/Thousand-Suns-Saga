"""
The nightly scan of the journal. Each rule only raises alerts : an admin decides, the false positives are common
(a family behind one IP, players of two timezones, a player who never sleeps).

The rules read at least their lookback, and all that happened since the last clean scan if it was longer ago : a day
without scan, or a changed hour, leaves no hole.
"""

import logging
from collections import defaultdict
from datetime import timedelta
from itertools import combinations, groupby
from statistics import median, pstdev

from dateutil import tz
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from anticheat.models import ActionLog, LoginLog, Scan
from backend.models import FINISHED_SERVER_STATUSES, CommandantAccount, Server
from data.admin import raise_alert
from database.schemas import server_schema
from game.models import EntenteMember


logger = logging.getLogger(__name__)

RETENTION_DAYS = 90  # Personal data : the journal is not kept longer
SCAN_LATE_AFTER_HOURS = 48

MAX_USERS_ON_SHARED_IP = 8  # More is a school or a phone operator, not the accounts of one person

ALTERNATING_BUCKET_MINUTES = 10
ALTERNATING_MIN_BUCKETS = 12
ALTERNATING_MIN_HANDOVERS = 5

BOT_MIN_GAPS = 50
BOT_MAX_REGULARITY = 0.2  # Standard deviation of the gaps over their mean : a human is above 1, as he plays in bursts
BOT_FAST_MIN_GAPS = 100
BOT_FAST_MEDIAN_SECONDS = 1
NO_SLEEP_MIN_SPAN_HOURS = 48
NO_SLEEP_MAX_PAUSE_HOURS = 4

BLIND_POST_WITHOUT_PAGE_MINUTES = 30  # A page left open may stay so for long, hence the two limits below
BLIND_POST_MIN = 20
BLIND_POST_MIN_RATIO = 0.8

REFUSED_ACTIONS_MIN = 20


def _players(server):
    # The superusers test with as many accounts as they want
    return dict(CommandantAccount.objects.filter(server=server, status='active', user__is_superuser=False).values_list('user_id', 'commandant_id'))


def _names(users):
    return dict(User.objects.filter(pk__in=users).values_list('pk', 'username'))


def shared_ip(server, since):
    players = _players(server)

    connections = set(ActionLog.objects.filter(server=server, date__gte=since, user__in=players, ip__isnull=False)
                      .values_list('user_id', 'ip', 'fingerprint').distinct())
    connections |= set(LoginLog.objects.filter(date__gte=since, success=True, user__in=players, ip__isnull=False)
                       .values_list('user_id', 'ip', 'fingerprint').distinct())

    users_of_ip = defaultdict(set)
    for user, ip, _fingerprint in connections:
        users_of_ip[ip].add(user)

    pairs = defaultdict(list)
    for ip, users in users_of_ip.items():
        if len(users) <= MAX_USERS_ON_SHARED_IP:
            for pair in combinations(sorted(users), 2):
                pairs[pair].append(ip)

    fingerprints = defaultdict(set)
    for user, ip, user_fingerprint in connections:
        fingerprints[user, ip].add(user_fingerprint)

    ententes = defaultdict(set)
    with server_schema(server):
        for commandant, entente in EntenteMember.objects.filter(status='member').values_list('commandant_id', 'entente_id'):
            ententes[commandant].add(entente)

    names = _names({user for pair in pairs for user in pair})
    for (first, second), ips in pairs.items():
        same_browser = any(fingerprints[first, ip] & fingerprints[second, ip] for ip in ips)
        same_entente = bool(ententes[players[first]] & ententes[players[second]])
        raise_alert(server, 'shared_ip', f'{names[first]} + {names[second]}',
                    'high' if same_browser and same_entente else 'medium' if same_browser else 'low',
                    f'{names[first]} et {names[second]} jouent depuis la même IP'
                    + (', avec le même navigateur' if same_browser else '') + (', dans la même entente' if same_entente else ''),
                    {'ips': sorted(ips), 'same_browser': same_browser, 'same_entente': same_entente})


def alternating_accounts(server, since):
    # Never at the same time, and one takes over just after the other : one person going from one account to the other
    buckets = defaultdict(set)
    bucket_seconds = ALTERNATING_BUCKET_MINUTES * 60
    actions = ActionLog.objects.filter(server=server, date__gte=since, user__in=_players(server)).values_list('user_id', 'date')
    for user, date in actions.iterator():
        buckets[user].add(int(date.timestamp()) // bucket_seconds)

    # shortcut: compares every pair of players, enough for a few thousands of them. Above, only compare the accounts sharing something.
    players = [user for user, user_buckets in buckets.items() if len(user_buckets) >= ALTERNATING_MIN_BUCKETS]
    found = []
    for first, second in combinations(sorted(players), 2):
        if not buckets[first] & buckets[second]:
            handovers = sum(bucket + 1 in buckets[second] for bucket in buckets[first]) + sum(bucket + 1 in buckets[first] for bucket in buckets[second])
            if handovers >= ALTERNATING_MIN_HANDOVERS:
                found.append((first, second, handovers))

    names = _names({user for first, second, _handovers in found for user in (first, second)})
    for first, second, handovers in found:
        raise_alert(server, 'alternating_accounts', f'{names[first]} + {names[second]}', 'low',
                    f'{names[first]} et {names[second]} ne jouent jamais ensemble et se relaient ({handovers} relais)', {'handovers': handovers})


def bots(server, since):
    # Replays the actions of each player in order : the heaviest of the rules, kept on a short lookback
    actions = (ActionLog.objects.filter(server=server, date__gte=since, user__in=_players(server))
               .order_by('user_id', 'date').values_list('user_id', 'date', 'method'))
    blind_post_limit = timedelta(minutes=BLIND_POST_WITHOUT_PAGE_MINUTES)

    alerts = []
    for user, user_actions in groupby(actions.iterator(), key=lambda action: action[0]):
        gaps, nb_posts, nb_blind_posts, previous, last_page = [], 0, 0, None, None

        for _user, date, method in user_actions:
            if previous:
                gaps.append((date - previous).total_seconds())
            previous = date
            if method == 'POST':
                nb_posts += 1
                nb_blind_posts += last_page is None or date - last_page > blind_post_limit
            else:
                last_page = date

        if len(gaps) >= BOT_MIN_GAPS and sum(gaps):
            regularity = pstdev(gaps) / (sum(gaps) / len(gaps))
            if regularity < BOT_MAX_REGULARITY:
                alerts.append((user, 'bot_regular', 'high', f'actions à intervalles réguliers (écart relatif {regularity:.2f})'))

        if len(gaps) >= BOT_FAST_MIN_GAPS and median(gaps) < BOT_FAST_MEDIAN_SECONDS:
            alerts.append((user, 'bot_fast', 'medium', f'actions enchaînées en moins de {BOT_FAST_MEDIAN_SECONDS} s ({len(gaps)} actions)'))

        if sum(gaps) >= NO_SLEEP_MIN_SPAN_HOURS * 3600 and max(gaps) < NO_SLEEP_MAX_PAUSE_HOURS * 3600:
            alerts.append((user, 'no_sleep', 'medium', f'aucune pause de {NO_SLEEP_MAX_PAUSE_HOURS} h en {sum(gaps) / 3600:.0f} h de jeu'))

        if nb_posts >= BLIND_POST_MIN and nb_blind_posts / nb_posts >= BLIND_POST_MIN_RATIO:
            alerts.append((user, 'blind_posts', 'medium', f"{nb_blind_posts} ordres sur {nb_posts} envoyés sans afficher de page : appels directs à l'API"))

    names = _names({alert[0] for alert in alerts})
    for user, rule, severity, message in alerts:
        raise_alert(server, rule, names[user], severity, names[user] + ' : ' + message)


def refused_actions(server, since):
    # The interface doesn't offer what is refused : probing of the ids, of the map, or forged parameters
    refused = (ActionLog.objects.filter(server=server, date__gte=since, status__gte=400, user__in=_players(server))
               .values('user_id', 'path').annotate(nb=Count('id')).filter(nb__gte=REFUSED_ACTIONS_MIN))
    refused = list(refused)
    names = _names({row['user_id'] for row in refused})
    for row in refused:
        raise_alert(server, 'refused_actions', f"{names[row['user_id']]} : {row['path']}", 'low',
                    f"{names[row['user_id']]} : {row['nb']} actions refusées sur {row['path']}", {'nb': row['nb']})


# With the days they read back at least
RULES = ((shared_ip, 7), (alternating_accounts, 7), (bots, 3), (refused_actions, 1))


def scan_server(scan, last_scan_date, now):
    errors = []
    for rule, lookback_days in RULES:
        since = now - timedelta(days=lookback_days)
        try:
            with transaction.atomic():  # A broken rule loses its own alerts, not the ones of the others
                rule(scan.server_id, min(since, last_scan_date) if last_scan_date else since)
        except Exception as error:
            logger.exception('Anticheat : rule %s failed on %s', rule.__name__, scan.server_id)
            errors.append(f'{rule.__name__} : {error}')

    Scan.objects.filter(pk=scan.pk).update(finished_at=timezone.now(), errors='\n'.join(errors))


def local_time(server, now):
    return now.astimezone(tz.gettz(server.timezone))


def scannable_servers():
    # Nothing to find on the servers of the admins or when the game is over
    return Server.objects.exclude(status__in=(*FINISHED_SERVER_STATUSES, 'test'))


def scan_due_servers(now=None):
    # Run every hour, to find out here if each server is due. Its hour is read at each run and not given to the system
    # scheduler : an hour changed by hand in the database applies from the next run, without anything else to change.
    now = now or timezone.now()
    scanned = []

    for server in scannable_servers():
        local_now = local_time(server, now)
        if local_now.hour != server.hour_anticheat_checks:
            continue

        last_scan = Scan.objects.filter(server=server, finished_at__isnull=False, errors='').order_by('-started_at').first()
        scan, created = Scan.objects.get_or_create(server=server, local_date=local_now.date(), defaults={'started_at': now})
        if created:  # Otherwise already done today, by an overlapping run or before the hour was changed
            scan_server(scan, last_scan.started_at if last_scan else None, now)
            scanned.append(server.server_name)

    return scanned


def purge_old_logs(now=None):
    limit = (now or timezone.now()) - timedelta(days=RETENTION_DAYS)
    ActionLog.objects.filter(date__lt=limit).delete()
    LoginLog.objects.filter(date__lt=limit).delete()


def scans_status(now=None):
    # For the admins : the hour really read by the scan, and if it runs at all. Nothing else would tell that the system scheduler is missing.
    now = now or timezone.now()
    status = []
    for server in scannable_servers().order_by('server_name'):
        last_scan = Scan.objects.filter(server=server).order_by('-started_at').first()
        status.append({'server': server.server_name, 'hour': server.hour_anticheat_checks, 'timezone': server.timezone, 'last_scan': last_scan,
                       'late': not last_scan or now - last_scan.started_at > timedelta(hours=SCAN_LATE_AFTER_HOURS)})
    return status
