
import random


def random_combination(count=1):

    vowels = {
        '1': ["b", "c", "d", "f", "g", "h", "i", "j", "k", "l", "m", "n", "p", "q", "r", "s", "t", "v", "w", "x", "y", "z"],
        '2': ["a", "e", "o", "u"],
        '3': ["br", "cr", "dr", "fr", "gr", "pr", "str", "tr", "bl", "cl", "fl", "gl", "pl", "sl", "sc", "sk", "sm", "sn", "sp", "st", "sw", "ch", "sh", "th", "wh"],
        '4': ["ae", "ai", "ao", "au", "a", "ay", "ea", "ei", "eo", "eu", "e", "ey", "ua", "ue", "ui", "uo", "u", "uy", "ia", "ie", "iu", "io", "iy", "oa", "oe", "ou", "oi", "o", "oy"],
        '5': ["turn", "ter", "nus", "rus", "tania", "hiri", "hines", "gawa", "nides", "carro", "rilia", "stea", "lia", "lea", "ria", "nov", "phus", "mia", "nerth", "wei", "ruta", "tov", "zuno", "vis", "lara", "nia", "liv", "tera", "gantu", "yama", "tune", "ter", "nus", "cury", "bos", "pra", "thea", "nope", "tis", "clite"],
        '6': ["una", "ion", "iea", "iri", "illes", "ides", "agua", "olla", "inda", "eshan", "oria", "ilia", "erth", "arth", "orth", "oth", "illon", "ichi", "ov", "arvis", "ara", "ars", "yke", "yria", "onoe", "ippe", "osie", "one", "ore", "ade", "adus", "urn", "ypso", "ora", "iuq", "orix", "apus", "ion", "eon", "eron", "ao", "omia"]
    }

    mtx = [
        [1, 1, 2, 2, 5, 5],
        [2, 2, 3, 3, 6, 6],
        [3, 3, 4, 4, 5, 5],
        [4, 4, 3, 3, 6, 6],
        [3, 3, 4, 4, 2, 2, 5, 5],
        [2, 2, 1, 1, 3, 3, 6, 6],
        [3, 3, 4, 4, 2, 2, 5, 5],
        [4, 4, 3, 3, 1, 1, 6, 6],
        [3, 3, 4, 4, 1, 1, 4, 4, 5, 5],
        [4, 4, 1, 1, 4, 4, 3, 3, 6, 6]
    ]

    def fn(i):
        return random.randint(0, len(vowels[i]) - 1)

    ret = []

    for c in range(count):
        name = ''
        comp = mtx[c % len(mtx)]
        for i in range(len(comp) // 2):
            name += vowels[str(comp[i * 2])][fn(str(comp[i * 2 + 1]))]
        name.capitalize()

        ret.append(name.capitalize())

    if count == 1:
        return ret[0]

    return ret
