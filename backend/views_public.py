from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.utils import timezone
from django.views.decorators.http import require_safe


from backend.login import throttled_authenticate
from data import forums
from data import server_details
from data import cycles



def public_homepage(request):
    return render(request, 'public/public_homepage.html')


@require_safe
def discover_tss(request):
    return render(request, 'public/discover_tss.html')



def servers_list(request):

    # A player looking for a server must not read an old menu saying it isn't open yet
    server_details.refresh_servers_menu()

    servers = server_details.get_all_servers_details()
    for i in range(len(servers)):
        servers[i]['cycles'] = cycles.get_current_cycle(servers[i]['server_name'])
        servers[i]['open_since_days'] = (timezone.now() - servers[i]['opening_date']).days

    servers = sorted(servers, key=lambda d: d['opening_date'], reverse=True)


    return render(request, 'public/servers_list.html', {'servers_details': servers})



@require_safe
def archives(request):
    # Sector assemblies of the current and past servers, open to everybody and read only. The test servers are no part of it.

    server_names = server_details.get_servers_names(test_servers=False)
    server = request.GET.get('server')

    if server is None:
        servers = [details for details in server_details.get_all_servers_details() if details['server_name'] in server_names]
        servers.sort(key=lambda details: details['opening_date'], reverse=True)
        return render(request, 'public/archives.html', {'servers': servers})

    if server not in server_names:
        return redirect('/archives/')

    page = request.GET.get('page', 1)
    if 'topic_id' not in request.GET:
        topics = forums.get_topics(server, forums.get_forum_id(server, 'assembly'), page, None)
        return render(request, 'public/archives.html', {'archive_server': server, 'topics': topics})

    topic = forums.get_assembly_topic(server, request.GET['topic_id'])
    if topic is None:
        return redirect('/archives/')
    return render(request, 'public/archives.html', {'archive_server': server, 'topic': topic,
                                                    'posts': forums.get_posts(server, topic['id'], page, None)})




########################################################################################################################
# LOGIN / INSCRIPTION / RESET PASSWORD /  ...


def player_login(request):

    login_error = None

    if request.method == 'POST':
        user, login_error = throttled_authenticate(request)
        if user is not None:
            login(request, user)
            return redirect('/user_account/')

    return render(request, 'public/player_login.html', {'login_error': login_error})



def player_register(request):
    # The form is sent to the JSON API create_user by includes/form_submit_to_json_api.js
    return render(request, 'public/player_register.html')
