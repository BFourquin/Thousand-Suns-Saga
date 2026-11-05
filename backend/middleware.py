
from django.utils import translation

from backend.utils import get_request_user


class UserLanguageMiddleware:
    # Translate the whole request, views included, in the language of the player's account
    # Must be placed after AuthenticationMiddleware

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = get_request_user(request)
        if user and user.get('language'):
            translation.activate(user['language'])

        response = self.get_response(request)

        # This thread will serve other players
        translation.deactivate()
        return response
