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

from backend import views, views_public, views_admin
from backend import views_api_user, views_api_commandant


app_name = "admin"

urlpatterns = [

    ####################################################################################################################
    # BACKEND JSON API
    ####################################################################################################################

    # USERS
    path('create_user/', views_api_user.create_user),
    path('get_user/', views_api_user.get_user),

    # COMMANDANTS
    path('create_commandant/', views_api_commandant.create_commandant),
    path('get_commandant/', views_api_commandant.get_commandant),


    ####################################################################################################################
    # DJANGO WEB INTERFACE
    ####################################################################################################################

    # path('admin/', admin.site.urls),  # Django default admin interface, now useless

    path('', views_admin.admin_main_dashboard, name='admin_main_dashboard'), # TODO remove

    # PUBLIC
    #path('', views_public.public_lobby, name='public_lobby'),
    path('public_lobby/', views_public.public_lobby, name='public_lobby'),

    # ACCOUNT
    path('player_login/', views_public.player_login, name='player_login'),



    ####################################################################################################################

    # ADMIN GLOBAL INTERFACE
    path('admin_login/', views_admin.admin_login, name='admin_login'),
    path('admin_main_dashboard/', views_admin.admin_main_dashboard, name='admin_main_dashboard'),


    path('admin_user_accounts/', views_admin.admin_user_accounts, name='admin_user_accounts'),
    path('admin_user_details/', views_admin.admin_user_details, name='admin_user_details'),

    # ADMIN SERVER SPECIFIC INTERFACE
    path('admin_servers_states/', views_admin.admin_servers_states, name='admin_servers_states'),
        path('admin_servers_states_edit/', views_admin.admin_servers_states_edit, name='admin_servers_states_edit'),

    path('admin_geography/', views_admin.admin_geography, name='admin_geography'),
    path('admin_technology/', views_admin.admin_technology, name='admin_technology'),


]+ static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
