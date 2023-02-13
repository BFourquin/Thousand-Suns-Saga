
import random
from math import sqrt

from backend import utils
from data import map_generator, sectors, systems
from geography import mg_coordinate
from backend.utils import seed_convertor, probability_picker, random_picker


def random_pick_system_type(server, sector_type, system_seed):
    systems_type_probabilities = {}
    mg_params_sector_type = map_generator.get_mg_params_sector_type(server, sector_type)

    for var, value in mg_params_sector_type.items():
        if 'system_type_probability_' in var:
            var = var.replace('system_type_probability_', '')
            systems_type_probabilities[var] = value if value else 0

    system_type = utils.probability_picker(systems_type_probabilities, system_seed)
    return system_type


def generate_system(server, seed, system_type=None):

    # SEED USAGE
    # generator seed + sector x and y position + system x and y position

    # Pick system type if not preselected
    if not system_type:
        sector_type = sectors.get_sector_by_seed(server, seed[0:10])['sector_type']
        system_type = random_pick_system_type(server, sector_type, seed)

    new_system = {
        "_id": str(seed),
        "system_type": system_type,
        "system_coordinates": {},
    }  # Some values like pos_y, pos_x, sector_seed will be auto-added when querying db

    ####################################################################################################################
    # Generate all coordinates by types of planet/asteroid (telluric/asteroid/jovian...)

    # ##### Star(s) #####

    solar_generator_probs = map_generator.get_mg_system_type(server, system_type)

    # Get solar types probabilities according to system type
    solar_type_prob = {}
    for name, prob in solar_generator_probs.items():
        if 'solar_type_probability_' in name and prob is not None:
            solar_type_prob[name.replace('solar_type_probability_', '')] = prob

    solar_seed = int(seed + '00')  # Coordinate seed : add two zeroes for the sun

    star_type = probability_picker(solar_type_prob, random_number=solar_seed)
    mg_coordinate.create_coordinate(server, solar_seed, coordinate_type='star', subtype=star_type)
    new_system["system_coordinates"][str(solar_seed)] = star_type

    # Following planets and asteroids depend on star type
    planets_generator_probs = map_generator.get_mg_system_composition(server, star_type)
    planet_seed = solar_seed+1  # Seed of the following planet to be generated

    # ##### Telluric(s) #####

    # Random picking of number of tellurics planets in the system

    telluric_prob = {}
    for name, prob in planets_generator_probs.items():
        if 'prob_telluric_' in name and prob is not None:
            telluric_prob[name.replace('prob_telluric_', '')] = prob

    telluric_picker_seed = int(seed + '001')    # Coordinate seed : add two zeroes and a one for telluric picker
                                                # (will not be the real seed of the generated planets, as using it would
                                                # create determinism in following generations)
    nb_tellurics = int(probability_picker(telluric_prob, random_number=telluric_picker_seed))

    # Place the tellurics planets
    # TODO planet type
    for i in range(nb_tellurics):
        mg_coordinate.create_coordinate(server, planet_seed, coordinate_type='telluric', subtype='telluric')
        new_system["system_coordinates"][str(planet_seed)] = 'telluric'
        planet_seed += 1


    # ##### Asteroid belt #####

    # Random picking if asteroid belt

    telluric_prob = {}
    for name, prob in planets_generator_probs.items():
        if 'prob_asteroid_belt' in name and prob is not None:
            telluric_prob['prob_asteroid_belt'] = prob

    asteroid_belt_picker_seed = int(seed + '002')   # Coordinate seed : add two zeroes and a two for asteroid belt picker
                                                    # (will not be the real seed of the generated planets, as using it would
                                                    # create determinism in following generations)
    has_asteroid_belt = random_picker(telluric_prob, random_number=asteroid_belt_picker_seed)

    # Place the asteroid belt
    # TODO asteroid belt
    if has_asteroid_belt:
        mg_coordinate.create_coordinate(server, planet_seed, coordinate_type='asteroid_belt', subtype='asteroid_belt')
        new_system["system_coordinates"][str(planet_seed)] = 'asteroid_belt'
        planet_seed += 1


    # ##### Planetoid(s) #####

    # Random picking of number of planetoids in the system

    planetoid_prob = {}
    for name, prob in planets_generator_probs.items():
        if 'prob_planetoid_' in name and prob is not None:
            planetoid_prob[name.replace('prob_planetoid_', '')] = prob

    planetoid_picker_seed = int(seed + '003')    # Coordinate seed : add two zeroes and a 3 for planetoid picker
                                              # (will not be the real seed of the generated planets, as using it would
                                              # create determinism in following generations)
    nb_planetoids = int(probability_picker(planetoid_prob, random_number=planetoid_picker_seed))

    # Place the planetoids
    # TODO planetoid type
    for i in range(nb_planetoids):
        mg_coordinate.create_coordinate(server, planet_seed, coordinate_type='planetoid', subtype='planetoid')
        new_system["system_coordinates"][str(planet_seed)] = 'planetoid'
        planet_seed += 1


    # ##### Jovian(s) #####

    # Random picking of number of jovians planets in the system

    jovian_prob = {}
    for name, prob in planets_generator_probs.items():
        if 'prob_jovian_' in name and prob is not None:
            jovian_prob[name.replace('prob_jovian_', '')] = prob

    jovian_picker_seed = int(seed + '004')    # Coordinate seed : add two zeroes and a 4 for jovian picker
                                              # (will not be the real seed of the generated planets, as using it would
                                              # create determinism in following generations)
    nb_jovians = int(probability_picker(jovian_prob, random_number=jovian_picker_seed))

    # Place the jovians planets
    # TODO jovian type
    for i in range(nb_jovians):
        mg_coordinate.create_coordinate(server, planet_seed, coordinate_type='jovian', subtype='jovian')
        new_system["system_coordinates"][str(planet_seed)] = 'jovian'
        planet_seed += 1


    # ##### Oort cloud #####

    # Random picking if asteroid belt

    oort_cloud_prob = {}
    for name, prob in planets_generator_probs.items():
        if 'prob_oort_cloud' in name and prob is not None:
            oort_cloud_prob['prob_oort_cloud'] = prob

    oort_cloud_picker_seed = int(seed + '002')   # Coordinate seed : add two zeroes and a two for asteroid belt picker
                                                    # (will not be the real seed of the generated planets, as using it would
                                                    # create determinism in following generations)
    has_oort_cloud = random_picker(telluric_prob, random_number=oort_cloud_picker_seed)

    # Place the asteroid belt
    # TODO oort_cloud
    if has_oort_cloud:
        mg_coordinate.create_coordinate(server, planet_seed, coordinate_type='oort_cloud', subtype='oort_cloud')
        new_system["system_coordinates"][str(planet_seed)] = 'oort_cloud'
        planet_seed += 1

    return new_system