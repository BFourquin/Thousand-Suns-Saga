
from functools import wraps

from django.utils.translation import gettext as _
from django.http import JsonResponse



########################################################################################################################
# MODAL AND POPUP ALERTS
# FROM ADMINLTE : https://adminlte.io/themes/v3/pages/UI/modals.html


#def pop_up()



def api_pop_up(response, status):
    # Optionals parameters : "level", "title", "subtitle", "body", "autohide", "delay"
    # Their display is managed by includes/form_submit_to_json_api.js

    response['popup'] = True
    return JsonResponse(response, status=status)


########################################################################################################################
# REDIRECTION


def api_pop_up_and_redirect(response, status, redirect):
    response['redirect'] = redirect
    return api_pop_up(response, status)


########################################################################################################################
# AUTHENTICATION


def api_login_required(view_func):
    # login_required would redirect to an HTML page, unreadable by the AJAX caller

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return api_pop_up_and_redirect({"title": _("Session expirée, veuillez vous reconnecter"), "level": "warning"},
                                           status=401, redirect='/player_login/')
        return view_func(request, *args, **kwargs)
    return wrapper
