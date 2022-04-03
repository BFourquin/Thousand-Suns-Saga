

def request_params(request):
    # return parameters passed by both GET and POST methods
    params = request.POST.copy()
    params.update(request.GET)
    return params


def parameters_presents(params, request_params):
    # Verify if each wanted params are present in request

    # Single str as parameter
    if isinstance(params, str):
        return bool(params in request_params)

    # List of parameters
    for param in params:
        if not param in request_params:
            return False
    return True
