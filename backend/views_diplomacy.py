from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.template.response import TemplateResponse

from backend.decorators import add_cycle_info, commandant_required, log_player_action
from data import ententes
from data.commandant import get_commandant_names
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
        'can_create': ententes.can_create_entente(server, commandant['id']), 'error': error})


def _do_entente_action(request, server, commandant_id, entente_id):
    # Return False when the entente is gone with the order
    post = request.POST
    action = post.get('action')

    if action == 'apply':
        ententes.apply_to_entente(server, entente_id, commandant_id, post.get('application', ''))
    elif action == 'leave':
        ententes.leave_entente(server, entente_id, commandant_id)
    elif action in ('accept_invitation', 'decline_invitation'):
        ententes.answer_invitation(server, entente_id, commandant_id, action == 'accept_invitation')
    elif action in ('accept', 'refuse'):
        ententes.answer_application(server, entente_id, commandant_id, post.get('commandant_id'), action == 'accept')
    elif action == 'invite':
        ententes.invite_to_entente(server, entente_id, commandant_id, post.get('invited_name', ''))
    elif action == 'exclude':
        ententes.exclude_member(server, entente_id, commandant_id, post.get('commandant_id'))
    elif action == 'create_role':
        ententes.create_role(server, entente_id, commandant_id, post.get('role_name', ''), post.getlist('options'))
    elif action == 'update_role':
        ententes.update_role(server, entente_id, commandant_id, post.get('role_id'), post.get('role_name', ''), post.getlist('options'))
    elif action == 'delete_role':
        ententes.delete_role(server, entente_id, commandant_id, post.get('role_id'))
    elif action == 'set_role':
        ententes.set_member_role(server, entente_id, commandant_id, post.get('commandant_id'), post.get('role_id'))
    elif action == 'save':
        ententes.update_entente_description(server, entente_id, commandant_id, post.get('description', ''))
    elif action == 'transfer':
        ententes.transfer_ownership(server, entente_id, commandant_id, post.get('commandant_id'))
    elif action == 'dissolve':
        ententes.dissolve_entente(server, entente_id, commandant_id)
        return False
    return True


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
            return redirect(request.get_full_path() if _do_entente_action(request, server, commandant['id'], entente_id) else '/diplomacy/')
        except GameError as game_error:
            error = str(game_error)

    return TemplateResponse(request, 'game/entente.html', {
        'entente': entente, 'error': error,
        'commandant_names': get_commandant_names(server) if entente['can_invite'] else []})
