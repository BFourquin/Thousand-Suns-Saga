
import random


########################################################################################################################
# VIEWS FUNCTIONS

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


########################################################################################################################
# RANDOM FUNCTIONS


def probability_picker(probabilities, random_number=random.random()):

    # If not between 0 and 1, use the number as a seed
    if not 0 < random_number < 1:
        random_number = random.random()

    # Check if all cumulated probabilities equal 1, 0.01 rounding error tolerance
    total_prob = sum(probabilities.values())
    if not 0.99 <= total_prob <= 1.01:
        for key, value in probabilities.items():
            probabilities[key] = value / total_prob

    # Random probability affectation
    cumulated_prob = 0
    for key, value in probabilities.items():
        cumulated_prob += value
        if random_number < cumulated_prob:
            return key


def seed_convertor(*seeds):
    """
    Convert a list of int with a fixed length into a new int usable as a seed
    Arg : *(int, fixed length)
    Example : (13, 2), (8,3) => 13, 008 => 13008
    """
    str_seed = ''

    for seed in seeds:
        seed_int, seed_length = str(seed[0]), int(seed[1])

        if len(seed_int) > seed_length:
            print('WARNING :: Seed Generation :: '
                  'One of the seed components is longer than expected and had to be truncated '
                  '[', seed_int, '] (expected length:', seed_length, ')')

        while len(seed_int) < seed_length:
            seed_int = '0' + seed_int
        str_seed += seed_int

    if str_seed[0] == '0':
        print('WARNING :: Seed Generation :: '
              'The first digit of the seed is a zero and will be lost when casted in an integer [', str_seed, ']')

    return str_seed


def info_from_seed(seed):
    """Get back infos from a seed"""
    infos = {}
    if len(seed) >= 6:
        infos['server_seed'] = seed[0:6]
    if len(seed) >= 12:
        infos['sector_id'] = seed[0:12]
    if len(seed) >= 15:
        infos['pos_y'] = seed[12:15]
    if len(seed) >= 18:
        infos['pos_x'] = seed[15:18]
    if len(seed) >= 20:
        infos['pos_orbital'] = seed[18:20]
    return infos
