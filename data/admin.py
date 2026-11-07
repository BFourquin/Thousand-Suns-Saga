import hashlib
import logging
from functools import wraps

from django.db import DatabaseError, transaction
from django.db.models import F
from django.utils import timezone

from anticheat.models import ActionLog, Alert, LoginLog


logger = logging.getLogger(__name__)

MAX_LOGGED_PARAMS = 20


def client_ip(request):
    # shortcut: REMOTE_ADDR is the proxy behind a reverse proxy, every player would share one IP : read the real client IP when deploying that way
    return request.META.get('REMOTE_ADDR') or None


def fingerprint(request):
    # shortcut: only the headers, so common to all the players on the same browser : it only reinforces a shared IP. A cookie or a JS fingerprint would tell more
    headers = request.META.get('HTTP_USER_AGENT', '') + '|' + request.META.get('HTTP_ACCEPT_LANGUAGE', '')
    return hashlib.sha256(headers.encode()).hexdigest()[:16]


def loggable_params(request):
    # Ids and the kind of action : the other values are free texts, private messages among them, or passwords
    params = {**request.GET.dict(), **request.POST.dict()}
    params.pop('csrfmiddlewaretoken', None)
    return {key[:50]: value[:20] if value.isdecimal() or key == 'action' else '...' for key, value in list(params.items())[:MAX_LOGGED_PARAMS]}


def never_fails(function):
    # A failing journal must never cost the player his action. ValueError : psycopg refuses a null character.
    @wraps(function)
    def wrapper(*args, **kwargs):
        try:
            with transaction.atomic():
                return function(*args, **kwargs)
        except (DatabaseError, ValueError):
            logger.exception('Anticheat : %s failed', function.__name__)
    return wrapper


@never_fails
def log_action(request, server, commandant_id, status):
    ActionLog.objects.create(date=timezone.now(), server_id=server, user_id=request.user.id, commandant_id=commandant_id,
                             method=request.method[:10], path=request.path[:200], params=loggable_params(request),
                             status=status, ip=client_ip(request), fingerprint=fingerprint(request))


@never_fails
def log_login(request, username, user):
    LoginLog.objects.create(date=timezone.now(), user=user, username=username[:150], success=user is not None,
                            ip=client_ip(request), fingerprint=fingerprint(request))


def raise_alert(server, rule, subject, severity, message, details=None):
    now = timezone.now()
    alert, created = Alert.objects.get_or_create(server_id=server, rule=rule, subject=subject[:200], defaults={
        'severity': severity, 'message': message, 'details': details or {}, 'first_seen': now, 'last_seen': now})
    if not created:  # The admin's decision is kept
        Alert.objects.filter(pk=alert.pk).update(severity=severity, message=message, details=details or {}, last_seen=now, nb_seen=F('nb_seen') + 1)


@never_fails
def cheat_log(message, log, server, user, commandant):
    # What can't happen from the interface, seen when it happens. server has to exist.
    raise_alert(server, 'cheat_log', f'{message} : user {user}, commandant {commandant}', 'medium', message,
                {'log': log, 'user': user, 'commandant': commandant})


def get_alerts(max_closed=50):
    alerts = Alert.objects.order_by('-last_seen')
    return {'open': list(alerts.filter(is_open=True)), 'closed': list(alerts.filter(is_open=False)[:max_closed])}


def set_alert_open(alert_id, is_open, username):
    Alert.objects.filter(pk=alert_id).update(is_open=is_open, handled_by='' if is_open else username)
