from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.template.response import TemplateResponse

from backend.decorators import add_cycle_info, commandant_required, log_player_action
from data import ententes
from data.errors import GameError


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def diplomacy(request, server, commandant):

    error = None
    if request.method == 'POST':
        try:
            entente_id = ententes.found_entente(server, commandant['id'], request.POST.get('name', ''),
                                                request.POST.get('category', ''), request.POST.get('description', ''))
            return redirect(f'/entente/?entente_id={entente_id}')
        except GameError as game_error:
            error = str(game_error)

    return TemplateResponse(request, 'game/diplomacy.html', {
        'ententes': ententes.get_ententes(server, commandant['id']), 'categories': ententes.founded_categories(),
        'can_found': ententes.can_found_entente(server, commandant['id']), 'error': error})


@login_required(login_url='/player_login/')
@add_cycle_info
@log_player_action
@commandant_required
def entente(request, server, commandant):

    entente_id = request.GET.get('entente_id')
    entente = ententes.get_entente(server, entente_id, commandant['id'])
    if not entente:
        return redirect('/diplomacy/')

    error = None
    if request.method == 'POST':
        try:
            action = request.POST.get('action')
            if action == 'apply':
                ententes.apply_to_entente(server, entente_id, commandant['id'], request.POST.get('application', ''))
            elif action == 'leave':
                ententes.leave_entente(server, entente_id, commandant['id'])
            elif action == 'save':
                ententes.update_entente_description(server, entente_id, commandant['id'], request.POST.get('description', ''))
            elif action in ('accept', 'refuse'):
                ententes.answer_application(server, entente_id, commandant['id'], request.POST.get('commandant_id'), action == 'accept')
            elif action == 'exclude':
                ententes.exclude_member(server, entente_id, commandant['id'], request.POST.get('commandant_id'))
            elif action == 'dissolve':
                ententes.dissolve_entente(server, entente_id, commandant['id'])
                return redirect('/diplomacy/')
            return redirect(request.get_full_path())
        except GameError as game_error:
            error = str(game_error)

    return TemplateResponse(request, 'game/entente.html', {'entente': entente, 'error': error})
