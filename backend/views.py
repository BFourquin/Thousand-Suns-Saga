from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate, login, logout
from django.core.validators import validate_email
from bokeh.plotting import figure
from bokeh.embed import components


from backend.utils import request_params, parameters_presents
from data import server_details, user, technology, sectors, systems, coordinates, map_generator
