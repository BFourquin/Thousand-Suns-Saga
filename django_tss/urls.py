"""Thousand Suns Saga URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, re_path

from backend import views_public, views_game, views_admin, views_game_colonies, views_forums, views_diplomacy
from backend import views_api_user, views_api_commandant, views_api_buildings, views_api_research


app_name = "admin"

urlpatterns = [

    ####################################################################################################################
    # BACKEND JSON API
    ####################################################################################################################

    # USERS
    path('create_user/', views_api_user.create_user),

    # COMMANDANTS
    path('api_create_commandant/', views_api_commandant.api_create_commandant),

    # GEOGRAPHY
    path('api_sector_map/', views_game.api_sector_map),
    path('api_zone_deposits/', views_game.api_zone_deposits),
    path('api_system_bodies/', views_game.api_system_bodies),

    # BUILDINGS & DISTRICTS
    path('api_start_research/', views_api_research.api_start_research),
    path('api_build_district/', views_api_buildings.api_build_district),
    path('api_build_building/', views_api_buildings.api_build_building),
    path('api_delete_district/', views_api_buildings.api_delete_district),
    path('api_district_set_activation_percent/', views_api_buildings.api_district_set_activation_percent),



    ####################################################################################################################
    # DJANGO WEB INTERFACE
    ####################################################################################################################


    # PUBLIC

    path('', views_public.public_homepage, name='public_homepage'),
    path('public_homepage/', views_public.public_homepage, name='public_homepage'),
    path('discover_tss/', views_public.discover_tss, name='discover_tss'),

    path('player_login/', views_public.player_login, name='player_login'),
    path('player_register/', views_public.player_register, name='player_register'),


    path('servers_list/', views_public.servers_list, name='servers_list'),
    path('archives/', views_public.archives, name='archives'),



    # IN GAME
    path('user_account/', views_game.user_account, name='user_account'),
    path('themes/', views_game.themes, name='themes'),

    path('create_commandant/', views_game.create_commandant, name='create_commandant'),
    path('commandant_login/', views_game.commandant_login, name='commandant_login'),

    path('cycle_monitoring/', views_game.cycle_monitoring, name='cycle_monitoring'),

    path('resources/', views_game.resources, name='resources'),
    path('modifiers/', views_game.modifiers, name='modifiers'),
    path('technologies/', views_game.technologies, name='technologies'),

    path('colonies/', views_game_colonies.colonies, name='colonies'),
    path('colony/', views_game_colonies.colony, name='colony'),

    path('geography_system/', views_game.geography_system, name='geography_system'),
    path('geography_quadrant/', views_game.geography_quadrant, name='geography_quadrant'),
    path('geography_sector/', views_game.geography_sector, name='geography_sector'),
    path('geography_favourite/', views_game.geography_favourite, name='geography_favourite'),

    path('reports/', views_game.reports, name='reports'),
    path('report/', views_game.report, name='report'),

    path('diplomacy/', views_diplomacy.diplomacy, name='diplomacy'),
    path('entente/', views_diplomacy.entente, name='entente'),

    path('communication/', views_forums.communication, name='communication'),
    path('assembly/', views_forums.assembly, name='assembly'),
    path('hrp/', views_forums.hrp, name='hrp'),
    path('coalition/', views_forums.coalition, name='coalition'),
    path('forum/', views_forums.forum, name='forum'),
    path('topic/', views_forums.topic, name='topic'),
    path('topic_view/', views_forums.topic_view, name='topic_view'),
    path('player_forums/', views_forums.player_forums, name='player_forums'),
    path('player_forum_manage/', views_forums.player_forum_manage, name='player_forum_manage'),

    path('conversations/', views_forums.conversations_list, name='conversations'),
    path('conversation/', views_forums.conversation, name='conversation'),



    ####################################################################################################################

    path('admin/', admin.site.urls),  # TODO Remove # Django default admin interface, now useless

    # ADMIN GLOBAL INTERFACE
    path('admin_login/', views_admin.admin_login, name='admin_login'),
    path('admin_main_dashboard/', views_admin.admin_main_dashboard, name='admin_main_dashboard'),


    path('admin_user_accounts/', views_admin.admin_user_accounts, name='admin_user_accounts'),
    path('admin_user_details/', views_admin.admin_user_details, name='admin_user_details'),
    path('admin_player_control/', views_admin.admin_player_control, name='admin_player_control'),
    path('admin_map_trial/', views_admin.admin_map_trial, name='admin_map_trial'),

    # ADMIN SERVER SPECIFIC INTERFACE
    path('admin_cheat_alerts/', views_admin.admin_cheat_alerts, name='admin_cheat_alerts'),
    path('admin_servers_states/', views_admin.admin_servers_states, name='admin_servers_states'),
        path('admin_unblock_schedule/', views_admin.admin_unblock_schedule, name='admin_unblock_schedule'),
        path('admin_servers_states_edit/', views_admin.admin_servers_states_edit, name='admin_servers_states_edit'),

    path('admin_geography/', views_admin.admin_geography, name='admin_geography'),
    path('admin_technology/', views_admin.admin_technology, name='admin_technology'),
    path('admin_message_flags/', views_admin.admin_message_flags, name='admin_message_flags'),


    ] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)


####################################################################################################################
# MODULES
####################################################################################################################

if 'rosetta' in settings.INSTALLED_APPS:
    urlpatterns += [re_path(r'^rosetta/', include('rosetta.urls'))]

if 'hijack' in settings.INSTALLED_APPS:
    urlpatterns += [path('hijack/', include('hijack.urls'))]
