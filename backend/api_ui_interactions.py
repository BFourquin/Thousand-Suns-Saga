
from django.http import JsonResponse


########################################################################################################################
# REDIRECTION




########################################################################################################################
# MODAL AND POPUP ALERTS
# FROM ADMINLTE : https://adminlte.io/themes/v3/pages/UI/modals.html



def pop_up(response, status):
    # Based on "Toasts Examples built in AdminLTE"
    # https://adminlte.io/docs/3.0/javascript/toasts.html

    response['popup'] = True

    # Optionals parameters : "level", "title", "subtitle", "body", "autohide", "delay", "icon", "image"

    # Message level
    popup_class_level = {'success': 'bg-success', 'info': 'bg-info', 'warning': 'bg-warning', 'danger': 'bg-danger'}
    if 'level' in response and response['level'] in popup_class_level:
        response['class'] = popup_class_level[response['level']]

    # Default hiding:
    if not 'autohide' in response:
        response['autohide'] = True
    if not 'delay' in response:
        response['delay'] = 3000

    print(response, status)

    return JsonResponse(response, status=status)


def pop_up_and_redirect(response, status, redirect):
    response['redirect'] = redirect
    return pop_up(response, status)
