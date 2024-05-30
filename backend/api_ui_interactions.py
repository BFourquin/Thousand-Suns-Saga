
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

    # Optionals parameters : "title", "subtitle", "body", "autohide", "delay", "icon", "image"
    # Defaults :
    if not 'autohide' in response:
        response['autohide'] = True
    if not 'delay' in response:
        response['delay'] = 3000

    return JsonResponse(response, status=status)

