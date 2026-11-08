"""
The readable place of a sector, a system or a body, instead of its seed of 10, 16 or 18 digits :
    C6            the sector of the column C and the row 6, as on a chessboard (AA after Z)
    C6-12.55      the system at X 12, Y 55 in this sector
    C6-12.55-3    the body on its orbit 3 (0 : the star)
The seeds stay the keys of the game : this module only converts both ways. The 4 digits of the server, the same for every
place of a server, are left out of the readable form and taken back from the seed of the commandant.
"""

import re

SEED = re.compile(r'\d{10}(\d{6}(\d{2})?)?')
READABLE = re.compile(r'([A-Za-z]{1,3})(\d{1,3})(?:-(\d{1,2})\.(\d{1,2})(?:-(\d{1,2}))?)?')


def column(x):
    # 0 -> A, 25 -> Z, 26 -> AA
    letters = ''
    x += 1
    while x:
        x, rest = divmod(x - 1, 26)
        letters = chr(65 + rest) + letters
    return letters


def column_index(letters):
    x = 0
    for letter in letters.upper():
        x = x * 26 + ord(letter) - 64
    return x - 1


def readable(seed):
    # The readable place of a seed ; anything else is given back as it is
    seed = str(seed)
    if not SEED.fullmatch(seed):
        return seed
    text = f'{column(int(seed[7:10]))}{int(seed[4:7]) + 1}'
    if len(seed) >= 16:
        text += f'-{int(seed[13:16]):02}.{int(seed[10:13]):02}'
    if len(seed) == 18:
        text += f'-{int(seed[16:18])}'
    return text


def seed_of(text, server_seed):
    # The seed of a place given in any of its forms, its seed or its readable place. None if it is neither.
    # server_seed : any seed of the server, for its first 4 digits.
    text = str(text).strip()
    if SEED.fullmatch(text):
        return text
    found = READABLE.fullmatch(text)
    if not found or not server_seed or int(found[2]) < 1 or column_index(found[1]) > 999 or int(found[2]) > 1000:
        return None
    seed = f'{str(server_seed)[:4]}{int(found[2]) - 1:03}{column_index(found[1]):03}'
    if found[3] is not None:
        seed += f'{int(found[4]):03}{int(found[3]):03}'
    if found[5] is not None:
        seed += f'{int(found[5]):02}'
    return seed
