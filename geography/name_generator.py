
SYLLABLES = {
    1: ["b", "c", "d", "f", "g", "h", "i", "j", "k", "l", "m", "n", "p", "q", "r", "s", "t", "v", "w", "x", "y", "z"],
    2: ["a", "e", "o", "u"],
    3: ["br", "cr", "dr", "fr", "gr", "pr", "str", "tr", "bl", "cl", "fl", "gl", "pl", "sl", "sc", "sk", "sm", "sn", "sp", "st", "sw", "ch", "sh", "th", "wh"],
    4: ["ae", "ai", "ao", "au", "a", "ay", "ea", "ei", "eo", "eu", "e", "ey", "ua", "ue", "ui", "uo", "u", "uy", "ia", "ie", "iu", "io", "iy", "oa", "oe", "ou", "oi", "o", "oy"],
    5: ["turn", "ter", "nus", "rus", "tania", "hiri", "hines", "gawa", "nides", "carro", "rilia", "stea", "lia", "lea", "ria", "nov", "phus", "mia", "nerth", "wei", "ruta", "tov", "zuno", "vis", "lara", "nia", "liv", "tera", "gantu", "yama", "tune", "ter", "nus", "cury", "bos", "pra", "thea", "nope", "tis", "clite"],
    6: ["una", "ion", "iea", "iri", "illes", "ides", "agua", "olla", "inda", "eshan", "oria", "ilia", "erth", "arth", "orth", "oth", "illon", "ichi", "ov", "arvis", "ara", "ars", "yke", "yria", "onoe", "ippe", "osie", "one", "ore", "ade", "adus", "urn", "ypso", "ora", "iuq", "orix", "apus", "ion", "eon", "eron", "ao", "omia"],
}

# The syllables of a name. The two shortest patterns only make 3 520 and 4 200 names : too few for the systems of a map.
PATTERNS = ((3, 4, 5), (4, 3, 6), (3, 4, 2, 5), (2, 1, 3, 6), (4, 3, 1, 6), (3, 4, 1, 4, 5), (4, 1, 4, 3, 6))

ROMAN = ('', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII', 'XIII', 'XIV', 'XV', 'XVI', 'XVII',
         'XVIII', 'XIX', 'XX')


def system_name(r, taken):
    # A name no other system of the map has, drawn with the random.Random r ; taken : the names already given
    while True:
        name = ''.join(r.choice(SYLLABLES[part]) for part in r.choice(PATTERNS)).capitalize()
        if name not in taken:
            taken.add(name)
            return name


def body_name(system, orbit):
    # The star has the name of its system, its bodies its name and their orbit : Kyrion, Kyrion I, Kyrion II...
    return system if orbit == 0 else f'{system} {ROMAN[orbit] if orbit < len(ROMAN) else orbit}'
