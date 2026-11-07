
import hashlib

from django.contrib.auth import authenticate
from django.core.cache import cache
from django.utils.translation import gettext as _

from data.admin import client_ip, log_login


LOGIN_BLOCK_SECONDS = 15 * 60
LOGIN_MAX_FAILURES_PER_ACCOUNT = 5
LOGIN_MAX_FAILURES_PER_IP = 20


def login_failure_counters(request, username):
    # shortcut: the default cache is per process, use a shared cache when deploying on several workers
    ip = client_ip(request) or ''
    account = hashlib.sha256((ip + username.lower()).encode()).hexdigest()
    return (('login_failures_account_' + account, LOGIN_MAX_FAILURES_PER_ACCOUNT),
            ('login_failures_ip_' + ip, LOGIN_MAX_FAILURES_PER_IP))


def throttled_authenticate(request):
    # Return (user, error message) from the username and password of a POST request

    username = request.POST.get('username', '')
    counters = login_failure_counters(request, username)

    if any(cache.get(key, 0) >= limit for key, limit in counters):
        return None, _("Trop de tentatives de connexion, veuillez réessayer dans quelques minutes")

    user = authenticate(request, username=username, password=request.POST.get('password', ''))
    log_login(request, username, user)

    if user is None:
        for key, _limit in counters:
            cache.add(key, 0, LOGIN_BLOCK_SECONDS)
            cache.incr(key)
        return None, _("Identifiants incorrects")

    cache.delete(counters[0][0])
    return user, None
