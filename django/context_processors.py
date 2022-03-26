from data import server_details


def servers_details(request):

    game_servers = server_details.get_servers_names(open_servers=True, playable_servers=True, test_servers=False, old_servers=False, admin_visibility=True)
    test_servers = server_details.get_servers_names(open_servers=False, playable_servers=False, test_servers=True, old_servers=False, admin_visibility=True)
    old_servers = server_details.get_servers_names(open_servers=False, playable_servers=False, test_servers=False, old_servers=True, admin_visibility=True)

    return {'game_servers': game_servers, 'test_servers': test_servers, 'old_servers': old_servers}
