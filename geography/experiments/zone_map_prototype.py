"""
Prototype : a sector without tiles nor quadrants, cut into natural zones.

Standalone experiment, numpy + Pillow only (no Django, no database) :
    python geography/experiments/zone_map_prototype.py             every batch : 10 maps for 20, 50 and 100 players, 5 for 200
    python geography/experiments/zone_map_prototype.py 50          one batch : the maps for 50 players
    python geography/experiments/zone_map_prototype.py key 50      one map
    python geography/experiments/zone_map_prototype.py --check     determinism self-check
Each run writes into a new folder geography/experiments/output/gen N/, for each map : <key>_vierge.png (the systems only),
<key>_zones.png (zones, stars, homes, bottlenecks) and <key>_rapport.txt, then resume.txt for the whole run.

All the randomness comes from rng() / nprng() : the same secret gives the same map, and nothing shown to the players lets
anyone recompute it. Vortex rule assumed : two systems are linked when their distance is at most the range of the bigger star.
"""

import hashlib
import heapq
import math
import os
import random
import sys
import time
from collections import Counter, deque

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SECRET = os.environ.get('TSS_MAP_SECRET', 'secret-de-dev')  # In the game : the Excel seed and a salt from secrets/
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
BATCHES = ((20, 10), (50, 10), (100, 10), (200, 5))  # (players, maps)

CELL = 5                # Size of a zone cell, in units
DENSITY = 0.04          # Systems per unit² of galaxy, as today : 40 591 systems on 1000 x 1000
AREA_PER_PLAYER = 10_000  # Units² of galaxy per player, as today : about 100 players on 1000 x 1000
HALO_WIDTH = 40         # The thin and sparse halo around the galaxy, then the void
HOMES_PER_CRADLE = 10
CRADLE_RADIUS = 85      # A cradle has the area of a disc of this radius, whatever its shape
HOME_RING = 0.55        # The homes stand on a ring at this share of the cradle : nobody in the centre, nobody surrounded
HALO_GAP = 60           # Least distance between a cradle and the halo
CRADLE_GAP = 60         # Least distance between two cradles
FAR = 110               # A precious zone is at least this far (by travel) from every cradle...
SHARED = 35             # ...or its second cradle is at most this much (+ 25 %) farther than its first
WARP = 6                # The borders of the zones wave by this many units : no staircase of cells
BANK = 15               # No random big star this close to a rift : only the planned bridgeheads cross it
INF = 10 ** 9

# class : (share in an ordinary zone, vortex range in units, colour, size drawn)
STARS = {
    'M': (0.60, 6, (205, 115, 95), 0),
    'K': (0.15, 7, (225, 165, 115), 0),
    'G': (0.07, 8, (240, 230, 175), 0),
    'F': (0.04, 9, (240, 240, 225), 0),
    'white_dwarf': (0.03, 5, (175, 185, 235), 0),
    'nebula': (0.015, 6, (215, 115, 205), 0),
    'neutron': (0.0025, 6, (110, 240, 240), 1),
    'pulsar': (0.0008, 8, (110, 240, 240), 1),
    'magnetar': (0.0003, 8, (110, 240, 240), 1),
    'A': (0.025, 12, (225, 235, 255), 1),
    'B': (0.013, 15, (165, 185, 255), 2),
    'giant': (0.02, 16, (255, 170, 70), 2),
    'O': (0.005, 18, (130, 155, 255), 2),
    'wolf_rayet': (0.002, 20, (195, 115, 255), 2),
    'supergiant': (0.008, 26, (255, 80, 50), 3),
    'black_hole': (0.0, 32, (255, 255, 255), 3),  # Only at the centre of a black heart
}
CLASSES = list(STARS)
RANGE = np.array([STARS[c][1] for c in CLASSES])
BIG = {'A', 'B', 'giant', 'O', 'wolf_rayet', 'supergiant', 'black_hole'}
BIG_IDX = np.array([c in BIG for c in CLASSES])
STAR_NAMES = {'A': 'A', 'B': 'B', 'giant': 'Géante', 'O': 'O', 'wolf_rayet': 'Wolf-Rayet', 'supergiant': 'Supergéante',
              'black_hole': 'Trou noir'}

SYSTEM_TYPES = {'standard': 0.955, 'wilderness': 0.0095, 'habitable_poor': 0.02, 'habitable_medium': 0.01,
                'habitable_good': 0.0045, 'habitable_gaia': 0.0004, 'danger': 0.001, 'resources_rich': 0.001,
                'gas_rich': 0.001, 'scientific': 0.001}
TYPES = list(SYSTEM_TYPES) + ['native', 'vestige']
T = {name: i for i, name in enumerate(TYPES)}

BIG_STARS_SHY = {c: 0.4 for c in ('A', 'B', 'giant', 'O', 'wolf_rayet', 'supergiant')}


def kind(label, colour, density, power=1.0, cap=None, stars=None, types=None, noise=0.7):
    # density : relative to an ordinary zone. power : how fast it grows. cap : its largest radius.
    return dict(label=label, colour=colour, density=density, power=power, cap=cap, stars=stars or {}, types=types or {}, noise=noise)


ZONES = {
    'berceau': kind('Berceau', (70, 215, 120), 1.3, noise=0.12),
    'marche': kind('Marche', (165, 205, 80), 1.0, types={'habitable_poor': 2, 'habitable_medium': 1.5}),
    'plaine': kind('Plaine stellaire', (100, 105, 140), 0.9, 1.1),
    'oasis': kind('Oasis', (40, 230, 210), 1.2, 0.6, 45, types={'habitable_gaia': 25, 'habitable_good': 8, 'habitable_medium': 3}),
    'faille': kind('Faille', (120, 120, 150), 0.0),
    'abime': kind('Abîme', (70, 70, 190), 0.03),
    'route': kind('Route des géantes', (255, 125, 40), 0.0),
    'tete_de_pont': kind('Tête de pont', (250, 250, 170), 0.9),
    'carrefour': kind('Carrefour', (255, 95, 110), 1.2, 0.6, 45, stars={'O': 3, 'B': 3, 'supergiant': 3, 'giant': 2}),
    'nebuleuse_sombre': kind('Nébuleuse sombre', (140, 85, 180), 1.2, 0.9, stars={'nebula': 8, **BIG_STARS_SHY}),
    'debris': kind('Champ de débris', (175, 140, 100), 1.1, 0.9, types={'resources_rich': 8}),
    'amas_globulaire': kind('Amas globulaire', (230, 190, 110), 2.6, 0.8, 60,
                            stars={'M': 1.2, 'K': 1.5, 'white_dwarf': 3, 'giant': 2, 'O': 0.1, 'B': 0.2, 'A': 0.5, 'supergiant': 0.2},
                            types={'habitable_poor': 0.5, 'habitable_medium': 0.4, 'habitable_good': 0.3, 'resources_rich': 3}),
    'pouponniere': kind('Pouponnière stellaire', (245, 110, 215), 1.4, 0.9, 70,
                        stars={'O': 5, 'B': 4, 'A': 2.5, 'nebula': 6, 'white_dwarf': 0.1, 'M': 0.7},
                        types={'gas_rich': 6, 'habitable_poor': 0.3, 'habitable_medium': 0.3, 'habitable_good': 0.3}),
    'gazier': kind('Champ gazier', (90, 160, 245), 1.0, 0.9, types={'gas_rich': 25}),
    'veine': kind('Veine', (230, 140, 40), 1.1, 0.6, 45, types={'resources_rich': 30}),
    'anomalies': kind("Zone d'anomalies", (60, 220, 245), 0.8, 0.8, 60, stars={'neutron': 10, 'pulsar': 15, 'magnetar': 15},
                      types={'scientific': 25}),
    'coeur_noir': kind('Cœur noir', (175, 60, 235), 0.9, 0.8, 60, types={'danger': 25, 'scientific': 10}),
    'supernova': kind('Reste de supernova', (245, 80, 50), 0.7, 0.8, 65, stars={'neutron': 12, 'pulsar': 15, 'magnetar': 10, 'nebula': 5},
                      types={'danger': 12, 'resources_rich': 6, 'scientific': 4}),
    'sauvage': kind('Terres sauvages', (50, 155, 60), 0.8, 1.0, types={'wilderness': 12}),
    'amas_dense': kind('Amas dense', (255, 240, 160), 3.0, 1.2, 95, stars={'giant': 3, 'supergiant': 3, 'O': 3, 'B': 2.5, 'A': 1.5},
                       types={'resources_rich': 3, 'scientific': 3, 'habitable_good': 1.5, 'habitable_medium': 1.5}),
    'halo': kind('Halo', (75, 75, 95), 0.12),
    'vestiges': kind('Vestiges', (255, 215, 0), 0.6, 0.6, 30, types={'scientific': 5}),
}
STAMPED = {'halo', 'berceau', 'faille', 'tete_de_pont', 'abime', 'route'}  # Drawn with their shape, the others grow
FREE_ZONES = {'plaine': 22, 'sauvage': 10, 'debris': 8, 'gazier': 8, 'nebuleuse_sombre': 8, 'amas_globulaire': 8,
              'pouponniere': 6, 'anomalies': 5, 'supernova': 4}
PLAIN_ZONES = ('plaine', 'sauvage', 'debris', 'gazier')
DANGEROUS = {'supernova', 'anomalies', 'nebuleuse_sombre'}  # Never next to a cradle
WEB = {'plaine', 'marche', 'sauvage', 'gazier', 'debris', 'nebuleuse_sombre', 'pouponniere', 'anomalies', 'supernova'}  # Filaments and voids
# The zones worth a fight : never at the door of a single cradle
PRECIOUS = {'oasis', 'veine', 'carrefour', 'amas_dense', 'amas_globulaire', 'pouponniere', 'anomalies', 'supernova', 'coeur_noir', 'vestiges'}

# What every home finds around it : (system type or 'big' for a big star, from, to (units), at least, at most).
# The habitable worlds stay within half the spacing of the homes : nobody shares them, the floors and ceilings never fight.
KIT = (('big', 0, 16, 2, 2),
       ('habitable_medium', 3, 12, 1, 1),
       ('habitable_poor', 3, 12, 2, 2),
       ('habitable_good', 3, 12, 1, 1),
       ('habitable_gaia', 0, 30, 0, 0))
NEIGHBOURS = ((-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0), (-1, -1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (1, 1, 1.414))


########################################################################################################################
# TOOLS


def rng(key, *purpose):
    # A str seed is hashed by SHA-512 : the same on every machine and every run, unlike hash()
    return random.Random('|'.join(map(str, (SECRET, key, *purpose))))


def nprng(key, *purpose):
    digest = hashlib.sha256('|'.join(map(str, (SECRET, key, *purpose))).encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], 'big'))


def value_noise(g, shape, scales):
    # Smooth noise in [0, 1] : random grids of a few cells, enlarged and summed. scales : (size of a grid cell, weight)
    total = np.zeros(shape, np.float32)
    for scale, weight in scales:
        small = g.random((shape[0] // scale + 3, shape[1] // scale + 3)).astype(np.float32)
        big = Image.fromarray(small).resize((small.shape[1] * scale, small.shape[0] * scale), Image.BICUBIC)
        total += weight * np.asarray(big)[scale:scale + shape[0], scale:scale + shape[1]]
    total -= total.min()
    return total / max(float(total.max()), 1e-9)


def dilate(mask):
    out = mask.copy()
    out[1:] |= mask[:-1]
    out[:-1] |= mask[1:]
    wide = out.copy()
    wide[:, 1:] |= out[:, :-1]
    wide[:, :-1] |= out[:, 1:]
    return wide


def distance_from(mask, steps):
    # Distance in cells to the mask (8 neighbours), steps + 1 beyond
    distance = np.where(mask, 0, steps + 1)
    reached = mask.copy()
    for step in range(1, steps + 1):
        reached = dilate(reached)
        distance[(distance > step) & reached] = step
    return distance


def box_blur(a):
    p = np.pad(a, 1, mode='edge')
    return sum(p[1 + dy:1 + dy + a.shape[0], 1 + dx:1 + dx + a.shape[1]] for dy in (-1, 0, 1) for dx in (-1, 0, 1)) / 9


def max_flow(n, arcs, s, t):
    # Edmonds-Karp. Returns the flow and the nodes still reachable from s at the end (one side of the minimum cut).
    graph = [[] for _ in range(n)]
    to, cap = [], []
    for u, v, c in arcs:
        graph[u].append(len(to)); to.append(v); cap.append(c)
        graph[v].append(len(to)); to.append(u); cap.append(0)
    flow = 0
    while True:
        prev = [-1] * n
        prev[s] = -2
        queue = deque([s])
        while queue and prev[t] == -1:
            u = queue.popleft()
            for e in graph[u]:
                if cap[e] > 0 and prev[to[e]] == -1:
                    prev[to[e]] = e
                    queue.append(to[e])
        if prev[t] == -1:
            return flow, [p != -1 for p in prev]
        push, v = INF, t
        while v != s:
            push, v = min(push, cap[prev[v]]), to[prev[v] ^ 1]
        if push >= INF:  # A node is at the same time a source and a sink
            return INF, [p != -1 for p in prev]
        v = t
        while v != s:
            cap[prev[v]] -= push
            cap[prev[v] ^ 1] += push
            v = to[prev[v] ^ 1]
        flow += push


def stats(values):
    values = sorted(values)
    if not values:
        return '-'
    return f'min {values[0]:g} / médiane {values[len(values) // 2]:g} / max {values[-1]:g}'


class Crowded(Exception):
    # The cradles don't fit : the galaxy is drawn again, a bit larger
    pass


########################################################################################################################
# THE SECTOR


class Sector:

    def __init__(self, key, players, grow=1.0):
        self.key, self.players = key, players
        self.n_cradles = max(1, round(players / HOMES_PER_CRADLE))
        self.homes_per = [players // self.n_cradles + (k < players % self.n_cradles) for k in range(self.n_cradles)]
        self.core = self.draw_galaxy(players * AREA_PER_PLAYER * grow)
        self.gh, self.gw = self.core.shape
        self.H, self.W = self.gh * CELL, self.gw * CELL
        self.cy = (np.arange(self.gh) + 0.5) * CELL
        self.cx = (np.arange(self.gw) + 0.5) * CELL
        self.owner = np.full((self.gh, self.gw), -1, np.int32)
        self.zones = []
        self.forced = []  # (y, x, star class, role) : the stars placed on purpose
        self.bridges = []  # ((y, x), (y, x)) : the vortex planned across a rift or an abyss
        self.home_cradle = []  # The cradle of each home, in the order of their stars in self.forced
        self.timings = {}

    def draw_galaxy(self, area):
        # A few blobs, chained or gathered, sometimes with a bay cut into one : the sector has its own shape on each map.
        # The threshold of their sum gives exactly the area wanted, then only the main piece is kept, a halo strip around.
        r, g = rng(self.key, 'shape'), nprng(self.key, 'shape')
        base = math.sqrt(area / math.pi)
        chained = r.random() < 0.5
        blobs = [(0.0, 0.0, base * r.uniform(0.55, 0.85), r.uniform(1.0, 2.0), r.uniform(0, math.pi), 1.0)]
        heading = r.uniform(0, 2 * math.pi)
        for _ in range(r.randint(1, 5)):
            parent = blobs[-1] if chained else r.choice(blobs)
            heading = heading + r.uniform(-0.7, 0.7) if chained else r.uniform(0, 2 * math.pi)
            radius = base * r.uniform(0.4, 0.75)
            reach = 0.75 * (parent[2] + radius) * r.uniform(0.8, 1.1)
            blobs.append((parent[0] + reach * math.sin(heading), parent[1] + reach * math.cos(heading), radius,
                          r.uniform(1.0, 2.0), r.uniform(0, math.pi), 1.0))
        if r.random() < 0.4:  # A bay : a void that bites into one of the blobs
            y, x, radius = r.choice(blobs)[:3]
            side = r.uniform(0, 2 * math.pi)
            blobs.append((y + 0.9 * radius * math.sin(side), x + 0.9 * radius * math.cos(side), radius * r.uniform(0.35, 0.6), 1.0, 0.0, -1.2))
        y0 = min(b[0] - 2 * b[2] for b in blobs) - base
        x0 = min(b[1] - 2 * b[2] for b in blobs) - base
        gh = int((max(b[0] + 2 * b[2] for b in blobs) + base - y0) // CELL) + 1
        gw = int((max(b[1] + 2 * b[2] for b in blobs) + base - x0) // CELL) + 1
        cy, cx = (np.arange(gh) + 0.5) * CELL + y0, (np.arange(gw) + 0.5) * CELL + x0
        field = np.zeros((gh, gw))
        for y, x, radius, stretch, angle, weight in blobs:
            u = (cx[None, :] - x) * math.cos(angle) + (cy[:, None] - y) * math.sin(angle)
            v = -(cx[None, :] - x) * math.sin(angle) + (cy[:, None] - y) * math.cos(angle)
            field += weight * np.exp(-(u / (radius * math.sqrt(stretch))) ** 2 - (v / (radius / math.sqrt(stretch))) ** 2)
        field *= 1 + 0.3 * (2 * value_noise(g, (gh, gw), [(max(4, int(base / CELL / 3)), 1.0), (max(2, int(base / CELL / 10)), 0.3)]) - 1)

        def main_piece(threshold):
            # The piece of the galaxy around its strongest point
            inside = field >= threshold
            seen = np.zeros_like(inside)
            start = np.unravel_index(int(np.argmax(field)), field.shape)
            seen[start] = True
            queue = deque([start])
            while queue:
                i, j = queue.popleft()
                for ni, nj in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)):
                    if 0 <= ni < gh and 0 <= nj < gw and inside[ni, nj] and not seen[ni, nj]:
                        seen[ni, nj] = True
                        queue.append((ni, nj))
            return seen

        wanted = area / CELL / CELL
        low, high = float(field.min()), float(np.sort(field, axis=None)[-int(wanted)])
        core = main_piece(high)
        for _ in range(12):  # A lower threshold until the main piece alone has the area wanted
            if core.sum() >= 0.98 * wanted:
                break
            middle = (low + high) / 2
            piece = main_piece(middle)
            if piece.sum() > 1.05 * wanted:
                low = middle
            else:
                high, core = middle, piece
        rows, cols = np.nonzero(core)
        margin = (HALO_WIDTH + 30) // CELL
        return core[max(rows.min() - margin, 0):rows.max() + margin + 1, max(cols.min() - margin, 0):cols.max() + margin + 1]

    def dist(self, y, x):
        return np.hypot(self.cy[:, None] - y, self.cx[None, :] - x)

    def disc(self, y, x, radius):
        # The cells of a disc, in a window of the grid
        i0, i1 = max(int((y - radius) // CELL), 0), max(min(int((y + radius) // CELL) + 1, self.gh), 0)
        j0, j1 = max(int((x - radius) // CELL), 0), max(min(int((x + radius) // CELL) + 1, self.gw), 0)
        window = (slice(i0, i1), slice(j0, j1))
        return window, (self.cy[i0:i1, None] - y) ** 2 + (self.cx[None, j0:j1] - x) ** 2 <= radius ** 2

    def cell(self, y, x):
        return min(max(int(y // CELL), 0), self.gh - 1), min(max(int(x // CELL), 0), self.gw - 1)

    def add_zone(self, kind_name, y, x):
        self.zones.append({'kind': kind_name, 'y': float(y), 'x': float(x)})
        return len(self.zones) - 1

    def zone_kinds(self):
        return np.array([zone['kind'] for zone in self.zones])

    def kind_of_cells(self):
        return np.where(self.owner >= 0, self.zone_kinds()[np.maximum(self.owner, 0)], '')

    ####################################################################################################################
    # ZONES

    def layout(self):
        g = nprng(self.key, 'layout')
        self.core_area = float(self.core.sum()) * CELL * CELL
        rows, cols = np.nonzero(self.core)
        self.box = (rows.min() * CELL, (rows.max() + 1) * CELL, cols.min() * CELL, (cols.max() + 1) * CELL)
        self.depth = distance_from(~self.core, max(self.gh, self.gw) // 2 + 2) * CELL  # Distance to the halo, inside
        self.halo_dist = distance_from(self.core, HALO_WIDTH // CELL + 1) * CELL  # Distance to the galaxy, outside
        self.owner[~self.core] = self.add_zone('halo', 0, 0)
        self.place_cradles(g)
        self.place_rifts()
        self.place_abysses()
        self.travel()
        self.place_seeds()
        self.grow()
        self.keep_precious_fair()

    def cradle_shape(self, y, x, stretch, angle, bend, noise):
        # An ellipse of the area of a disc of CRADLE_RADIUS, stretched, turned, bent like a bean, with a waving border
        a, b = CRADLE_RADIUS * math.sqrt(stretch), CRADLE_RADIUS / math.sqrt(stretch)
        window, _ = self.disc(y, x, 1.3 * a)
        py, px = self.cy[window[0], None] - y, self.cx[None, window[1]] - x
        u = px * math.cos(angle) + py * math.sin(angle)
        v = -px * math.sin(angle) + py * math.cos(angle) + bend * u ** 2 / a
        return window, (u / a) ** 2 + (v / b) ** 2 <= (0.9 + 0.2 * noise[window]) ** 2

    def place_cradle_cells(self, window, inside, k):
        # Marked -2 - k until the zones of the cradles are created in their order
        self.owner[window][inside] = -2 - k
        return self.owner == -2 - k

    def ring_of_homes(self, y, x, stretch, angle, bend, count, r):
        # The homes, spread evenly on a ring inside the cradle : each one has the centre on one side, the outside on the other
        a, b = CRADLE_RADIUS * math.sqrt(stretch), CRADLE_RADIUS / math.sqrt(stretch)
        ring = []
        for s in range(720):
            t = s * 2 * math.pi / 720
            u, v = HOME_RING * a * math.cos(t), HOME_RING * b * math.sin(t)
            v -= bend * u ** 2 / a
            ring.append((y + u * math.sin(angle) + v * math.cos(angle), x + u * math.cos(angle) - v * math.sin(angle)))
        lengths = np.cumsum([0] + [math.dist(p, q) for p, q in zip(ring, ring[1:] + ring[:1])])
        phase = r.random()
        return [ring[min(int(np.searchsorted(lengths, (k + phase) / count * lengths[-1])), 719)] for k in range(count)]

    def place_cradles(self, g):
        r = rng(self.key, 'cradles')
        noise = value_noise(g, (self.gh, self.gw), [(6, 1.0)])
        n = self.n_cradles
        usable = np.flatnonzero(self.depth >= HALO_GAP + 0.4 * CRADLE_RADIUS)
        if len(usable) < 50 * n:
            raise Crowded
        ys, xs = self.cy[usable // self.gw], self.cx[usable % self.gw]
        # Centres spread evenly over the room the halo leaves : Lloyd's relaxation, from seeds drawn far from each other
        centres = [(ys[k], xs[k]) for k in [r.randrange(len(usable))]]
        while len(centres) < n:
            d2 = np.min([(ys - y) ** 2 + (xs - x) ** 2 for y, x in centres], axis=0)
            k = int(np.searchsorted(np.cumsum(d2), r.random() * d2.sum()))
            centres.append((ys[min(k, len(ys) - 1)], xs[min(k, len(xs) - 1)]))
        centres = np.array(centres)
        for _ in range(20):
            nearest = np.argmin((ys[:, None] - centres[None, :, 0]) ** 2 + (xs[:, None] - centres[None, :, 1]) ** 2, axis=1)
            for k in range(n):
                if (nearest == k).any():
                    centres[k] = ys[nearest == k].mean(), xs[nearest == k].mean()
        near = np.zeros((self.gh, self.gw), bool)  # Too close to a cradle already placed
        self.cradles = []
        order = sorted(range(n), key=lambda k: -self.depth[self.cell(*centres[k])])  # The inner ones first
        placed = {}
        for k in order:
            y, x = centres[k]
            # The cradle lies along its share of the room, as stretched as it, then less if it doesn't fit.
            # Too near the halo or another cradle, it slides towards the centre of the galaxy.
            sel = nearest == k
            cov = np.cov(np.stack([xs[sel], ys[sel]])) if sel.sum() > 2 else np.eye(2)
            values, vectors = np.linalg.eigh(cov)
            angle = math.atan2(vectors[1, 1], vectors[0, 1])
            elongation = math.sqrt(max(values[1], 1e-9) / max(values[0], 1e-9))
            bend = r.uniform(-0.35, 0.35)
            inward = math.atan2(self.H / 2 - y, self.W / 2 - x)
            found = None
            for slide in range(0, 80, 10):
                cy, cx = y + slide * math.sin(inward), x + slide * math.cos(inward)
                for stretch in (min(1.8, max(1.0, elongation * r.uniform(0.9, 1.3))), 1.4, 1.0):
                    for turn in (0, 0.1, -0.1, 0.25, -0.25, 0.5):
                        window, inside = self.cradle_shape(cy, cx, stretch, angle + turn * math.pi, bend, noise)
                        if inside.any() and self.depth[window][inside].min() >= HALO_GAP and not near[window][inside].any():
                            found = (cy, cx, stretch, angle + turn * math.pi, window, inside)
                            break
                    if found:
                        break
                if found:
                    break
            if not found:
                raise Crowded
            y, x, stretch, angle, window, inside = found
            centres[k] = (y, x)
            near |= distance_from(self.place_cradle_cells(window, inside, k), CRADLE_GAP // CELL) <= CRADLE_GAP // CELL
            placed[k] = (y, x, stretch, angle, bend)
        # The zones and the homes in the order of the cradles, whatever the order they were placed in
        for k in range(n):
            y, x, stretch, angle, bend = placed[k]
            zid = self.add_zone('berceau', y, x)
            self.owner[self.owner == -2 - k] = zid
            self.cradles.append(zid)
            for hy, hx in self.ring_of_homes(y, x, stretch, angle, bend, self.homes_per[k], r):
                self.forced.append((hy, hx, r.choice(('F', 'G', 'K')), 'monde_natal'))
                self.home_cradle.append(k)
        self.cradle_centres = [tuple(c) for c in centres.tolist()]
        self.cradle_mask = np.isin(self.owner, self.cradles)
        self.cradle_dist = distance_from(self.cradle_mask, 40) * CELL

    def place_rifts(self):
        r = rng(self.key, 'rifts')
        self.rifts, self.rift = [], np.zeros((self.gh, self.gw), bool)
        far = np.full((self.gh, self.gw), 999)

        def blocked(p):
            i, j = int(p[0] // CELL), int(p[1] // CELL)
            return not (0 <= i < self.gh and 0 <= j < self.gw) or self.depth[i, j] < 30 or self.cradle_dist[i, j] < 20 or far[i, j] < 70

        wanted, tries = round(self.core_area / 200_000), 0
        while len(self.rifts) < wanted and tries < 4 * wanted:
            tries += 1
            # Away from the halo, the cradles and the other rifts : two rifts side by side would only make a useless strip
            pool = np.flatnonzero((self.depth >= 80) & (self.cradle_dist >= 40) & (far >= 120))
            if not len(pool):
                break
            i, j = divmod(int(pool[r.randrange(len(pool))]), self.gw)
            start = (self.cy[i], self.cx[j])
            heading, half = r.uniform(0, 2 * math.pi), r.uniform(200, 450)
            sides = []
            for turn in (0, math.pi):
                p, h, side = start, heading + turn, []
                while len(side) * 8 < half:
                    h += r.gauss(0, 0.12)
                    # A rift bends around what it must avoid : it becomes a natural border between the cradles
                    for bend in (0, 0.3, -0.3, 0.6, -0.6, 0.9, -0.9, 1.2, -1.2):
                        q = (p[0] + 8 * math.sin(h + bend), p[1] + 8 * math.cos(h + bend))
                        if not blocked(q):
                            h += bend
                            break
                    else:
                        break
                    side.append(q)
                    p = q
                sides.append(side)
            points = sides[1][::-1] + [start] + sides[0]
            if len(points) < 25:  # Too short to be worth a detour : a few bridgeheads need room
                continue
            phase = r.uniform(0, 6.3)
            widths = [12 + 8 * (0.5 + 0.5 * math.sin(phase + k * 0.09)) for k in range(len(points))]
            zid = self.add_zone('faille', *points[len(points) // 2])
            for (y, x), w in zip(points, widths):
                window, inside = self.disc(y, x, w / 2 + 3)  # + 3 : no system closer than w across the rift
                self.owner[window][inside] = zid
                self.rift[window] |= inside
            self.rifts.append((zid, points, widths))
            far = distance_from(self.rift, 30) * CELL
        self.rift_dist = distance_from(self.rift, 30) * CELL
        self.bridge_points, self.skipped_bridgeheads = [], 0
        for _, points, widths in self.rifts:
            self.place_bridgeheads(r, points, widths)

    @staticmethod
    def normal(points, i):
        ty, tx = points[i + 1][0] - points[i - 1][0], points[i + 1][1] - points[i - 1][1]
        norm = math.hypot(ty, tx) or 1
        return tx / norm, -ty / norm

    def joins_regions(self, points, widths, i):
        # A bridgehead is only worth it between two real regions : not towards the halo nor a strip along another rift
        (y, x), w = points[i], widths[i]
        ny, nx = self.normal(points, i)
        for side in (1, -1):
            for d in (w / 2 + 12, w / 2 + 30, w / 2 + 50):
                ci, cj = int((y + side * ny * d) // CELL), int((x + side * nx * d) // CELL)
                if not (0 <= ci < self.gh and 0 <= cj < self.gw) or self.depth[ci, cj] < 20 or self.rift[ci, cj]:
                    return False
        return True

    def place_bridgeheads(self, r, points, widths):
        # A pair of big stars face each other across the rift : the only way to cross it. Not at its ends : one walks around them.
        ends = 8
        n = max(1, round(len(points) * 8 / 170))
        for k in range(n):
            target = ends + (k + 0.5) / n * (len(points) - 2 * ends)
            for offset in sorted(range(-12, 13), key=abs):
                i = int(target) + offset
                if ends <= i < len(points) - ends and self.joins_regions(points, widths, i):
                    break
            else:
                self.skipped_bridgeheads += 1
                continue
            (y, x), w = points[i], widths[i]
            ny, nx = self.normal(points, i)
            half = w / 2 + 2
            far = r.choice([c for c in ('giant', 'O', 'wolf_rayet', 'supergiant') if STARS[c][1] >= 2 * half + 1])
            sides = [(y + ny * half, x + nx * half), (y - ny * half, x - nx * half)]
            r.shuffle(sides)
            self.forced.append((*sides[0], far, 'tete_de_pont'))
            self.forced.append((*sides[1], r.choice(('A', 'B', 'giant', 'O')), 'tete_de_pont'))
            self.bridges.append((sides[0], sides[1]))
            self.bridge_points.append((y, x, w))
            zid = self.add_zone('tete_de_pont', y, x)
            window, inside = self.disc(y, x, 20)
            self.owner[window][inside & ~self.rift[window] & ~self.cradle_mask[window]] = zid

    def place_abysses(self):
        r = rng(self.key, 'abysses')
        shape = value_noise(nprng(self.key, 'abysses'), (self.gh, self.gw), [(10, 1.0)])
        for _ in range(round(self.core_area / 450_000)):
            pool = np.flatnonzero(self.core & (self.owner == -1))
            if not len(pool):
                break
            for _ in range(300):
                radius = r.uniform(55, 90)
                margin = radius * 1.25
                i, j = divmod(int(pool[r.randrange(len(pool))]), self.gw)
                if self.depth[i, j] >= margin + 30 and self.cradle_dist[i, j] >= margin + 40 and self.rift_dist[i, j] >= margin + 10:
                    break
            else:
                continue
            y, x = self.cy[i], self.cx[j]
            zid = self.add_zone('abime', y, x)
            window, inside = self.disc(y, x, margin)
            d = np.hypot(self.cy[window[0], None] - y, self.cx[None, window[1]] - x)
            self.owner[window][inside & (d <= radius * (0.75 + 0.5 * shape[window])) & (self.owner[window] == -1)] = zid
            if r.random() < 0.6:
                self.place_road(r, y, x, margin + 8, zid)

    def place_road(self, r, y, x, reach, abyss):
        # A road of giants crosses the abyss : a bow and a few waves, a relay every 12 units at most along it
        angle = r.uniform(0, math.pi)
        dy, dx = math.sin(angle), math.cos(angle)
        bow, wave, phase = r.uniform(-0.5, 0.5) * reach, r.uniform(3, 8), r.uniform(0, 2 * math.pi)
        curve = []
        for s in range(201):
            t = s / 200
            side = bow * 4 * t * (1 - t) + wave * math.sin(phase + 3 * math.pi * t)
            along = -reach + 2 * reach * t
            curve.append((y + along * dy - side * dx, x + along * dx + side * dy))
        relays, travelled = [curve[0]], 0.0
        for p, q in zip(curve, curve[1:]):
            travelled += math.dist(p, q)
            if travelled >= 12:
                relays.append(q)
                travelled = 0.0
        if math.dist(relays[-1], curve[-1]) > 3:
            relays.append(curve[-1])
        for relay in relays:
            self.forced.append((*relay, r.choice(('giant', 'O', 'supergiant', 'wolf_rayet')), 'route'))
        self.bridges += list(zip(relays, relays[1:]))
        road = self.add_zone('route', y, x)
        for p in curve[::4]:
            window, inside = self.disc(*p, 9)
            self.owner[window][inside & (self.owner[window] == abyss)] = road

    def travel(self):
        # Travel distance from the cradles, cell by cell, the rifts crossed only at the bridgeheads :
        # t1 to the nearest cradle, t2 to the second one
        kinds = self.kind_of_cells()
        cost = np.ones((self.gh, self.gw))
        cost[~self.core] = 3
        cost[kinds == 'abime'] = 6
        cost[self.halo_dist > HALO_WIDTH] = np.inf
        cost[self.rift] = np.inf
        for y, x, w in self.bridge_points:
            window, inside = self.disc(y, x, w / 2 + 6)
            cost[window][inside] = 1
        cost = cost.tolist()
        best = [[] for _ in range(self.gh * self.gw)]
        heap = [(0.0, k, int(i), int(j)) for k, zid in enumerate(self.cradles) for i, j in zip(*np.nonzero(self.owner == zid))]
        heapq.heapify(heap)
        while heap:
            d, src, i, j = heapq.heappop(heap)
            settled = best[i * self.gw + j]
            if len(settled) == 2 or (settled and settled[0][1] == src):
                continue
            settled.append((d, src))
            for di, dj, step in NEIGHBOURS:
                ni, nj = i + di, j + dj
                if 0 <= ni < self.gh and 0 <= nj < self.gw and cost[ni][nj] != math.inf:
                    other = best[ni * self.gw + nj]
                    if len(other) < 2 and not (other and other[0][1] == src):
                        heapq.heappush(heap, (d + step * CELL * cost[ni][nj], src, ni, nj))
        self.t1 = np.array([s[0][0] if s else np.inf for s in best]).reshape(self.gh, self.gw)
        self.t2 = np.array([s[1][0] if len(s) > 1 else np.inf for s in best]).reshape(self.gh, self.gw)
        self.s1 = np.array([s[0][1] if s else -1 for s in best]).reshape(self.gh, self.gw)
        self.s2 = np.array([s[1][1] if len(s) > 1 else -1 for s in best]).reshape(self.gh, self.gw)
        # Precious content : far from every cradle, or about as near to two of them
        with np.errstate(invalid='ignore'):
            self.shared = np.where(np.isfinite(self.t2), self.t2 - self.t1, np.inf)
        self.fair = np.isfinite(self.t1) & ((self.t1 >= FAR) | (self.shared <= SHARED + 0.25 * self.t1))

    def place_seeds(self):
        g, r = nprng(self.key, 'seeds'), rng(self.key, 'seeds')
        jitter = value_noise(g, (self.gh, self.gw), [(6, 1.0)])
        free = self.owner == -1
        nearest = self.cradle_dist + 60.0  # Distance to the nearest seed : the cradles count as seeds

        def seed(kind_name, y, x):
            nonlocal nearest
            self.add_zone(kind_name, y, x)
            nearest = np.minimum(nearest, self.dist(y, x))

        def pick(kind_name, count, score, ok, spacing):
            ok = ok & free & np.isfinite(score)
            chosen = 0
            for flat in np.argsort(np.where(ok, score, np.inf), axis=None)[:int(ok.sum())]:
                i, j = divmod(int(flat), self.gw)
                if chosen < count and nearest[i, j] >= spacing:
                    seed(kind_name, self.cy[i], self.cx[j])
                    chosen += 1

        inner = self.depth >= 60
        shared = self.shared
        far = np.isfinite(self.t1) & (self.t1 >= FAR)
        n = self.n_cradles
        # The prizes stand where two or three cradles are at the same distance : nobody gets them at their door
        pick('amas_dense', max(1, round(self.core_area / 800_000)), shared + 40 * jitter, self.fair & (self.t1 >= 120) & (self.depth >= 150), 150)
        pick('oasis', round(0.6 * n), shared + 40 * jitter, self.fair & (self.t1 >= 50) & inner, 120)
        pick('carrefour', round(0.4 * n), shared + 60 * jitter, self.fair & (self.t1 >= 60) & inner, 110)
        pick('veine', round(0.4 * n), shared + 80 * jitter - 40 * (self.rift_dist < 60), self.fair & (self.t1 >= 60) & inner, 110)
        if r.random() < 0.7:
            pick('coeur_noir', 1, -np.minimum(self.t1, 400) + 100 * jitter, far & (self.t1 >= FAR + 40) & inner, 150)

        # The vestiges of the hunting mode : on the east side, behind a rift if possible, from a start on the west side
        y0, y1, x0, x1 = self.box
        east = self.cx[None, :] > x0 + 0.7 * (x1 - x0)
        candidates = np.flatnonzero(free & east & (self.depth >= 40) & (nearest >= 100) & self.fair)
        best = None
        for flat in g.choice(candidates, size=min(200, len(candidates)), replace=False) if len(candidates) else ():
            i, j = divmod(int(flat), self.gw)
            line = np.linspace(0, 1, 300)
            ys, xs = (y0 + y1) / 2 + line * (self.cy[i] - (y0 + y1) / 2), x0 + line * (self.cx[j] - x0)
            crossed = bool(self.rift[np.clip(ys // CELL, 0, self.gh - 1).astype(int), np.clip(xs // CELL, 0, self.gw - 1).astype(int)].any())
            if best is None or (crossed, self.cx[j]) > best[0]:
                best = ((crossed, self.cx[j]), i, j)
        if best:
            seed('vestiges', self.cy[best[1]], self.cx[best[2]])

        # Marches between neighbouring cradles
        for a in range(n):
            for b in range(a + 1, n):
                (ya, xa), (yb, xb) = self.cradle_centres[a], self.cradle_centres[b]
                i, j = self.cell((ya + yb) / 2, (xa + xb) / 2)
                if math.dist((ya, xa), (yb, xb)) < 1.4 * math.sqrt(self.core_area / n) and free[i, j] and nearest[i, j] >= 70:
                    seed('marche', self.cy[i], self.cx[j])

        names, weights = list(FREE_ZONES), list(FREE_ZONES.values())
        for flat in g.permutation(np.flatnonzero(free)):
            i, j = divmod(int(flat), self.gw)
            if nearest[i, j] >= 100:
                kind_name = r.choices(names, weights)[0]
                if kind_name in PRECIOUS and not self.fair[i, j]:
                    kind_name = r.choice(PLAIN_ZONES)
                if kind_name in DANGEROUS and self.t1[i, j] < 70:
                    kind_name = 'plaine'
                if kind_name == 'plaine' and self.t1[i, j] < 40:
                    kind_name = 'marche'
                seed(kind_name, self.cy[i], self.cx[j])

    def grow(self):
        # The zones grow together from their seed, faster or slower depending on the place : natural borders
        g = nprng(self.key, 'growth')
        cost = (0.5 + value_noise(g, (self.gh, self.gw), [(4, 0.5), (16, 1.0)])).tolist()
        cap_noise = value_noise(g, (self.gh, self.gw), [(5, 1.0)]).tolist()
        self.expand([i for i, zone in enumerate(self.zones) if zone['kind'] not in STAMPED], cost, cap_noise)
        while (self.owner == -1).any():  # The pockets no zone reached become plains
            nearest, new = np.full((self.gh, self.gw), np.inf), []
            for flat in g.permutation(np.flatnonzero(self.owner == -1)):
                i, j = divmod(int(flat), self.gw)
                if nearest[i, j] >= 100:
                    new.append(self.add_zone('marche' if self.t1[i, j] < 40 else 'plaine', self.cy[i], self.cx[j]))
                    nearest = np.minimum(nearest, self.dist(self.cy[i], self.cx[j]))
            self.expand(new, cost, cap_noise)
        self.merge_small_zones()

    def expand(self, zone_ids, cost, cap_noise):
        owner = self.owner.tolist()
        heap = []
        for zid in zone_ids:
            i, j = self.cell(self.zones[zid]['y'], self.zones[zid]['x'])
            heap.append((0.0, zid, i, j))
        heapq.heapify(heap)
        while heap:
            d, zid, i, j = heapq.heappop(heap)
            if owner[i][j] != -1:
                continue
            owner[i][j] = zid
            zone = self.zones[zid]
            spec = ZONES[zone['kind']]
            for di, dj, step in NEIGHBOURS:
                ni, nj = i + di, j + dj
                if 0 <= ni < self.gh and 0 <= nj < self.gw and owner[ni][nj] == -1:
                    if spec['cap'] and math.hypot(self.cy[ni] - zone['y'], self.cx[nj] - zone['x']) > spec['cap'] * (0.8 + 0.4 * cap_noise[ni][nj]):
                        continue
                    heapq.heappush(heap, (d + step * cost[ni][nj] / spec['power'], zid, ni, nj))
        self.owner = np.array(owner, np.int32)

    def merge_small_zones(self, minimum=12):
        sizes = np.bincount(self.owner.ravel(), minlength=len(self.zones))
        for zid in np.flatnonzero((sizes > 0) & (sizes < minimum)):
            if self.zones[zid]['kind'] in STAMPED:
                continue
            mask = self.owner == zid
            around = [z for z in self.owner[dilate(mask) & ~mask].tolist() if self.zones[z]['kind'] not in STAMPED]
            if around:
                self.owner[mask] = Counter(around).most_common(1)[0][0]

    def keep_precious_fair(self):
        # A precious zone grown too near a single cradle becomes ordinary. Its distance to a cradle : from its nearest cell.
        self.downgraded, self.precious = [], []
        for zid, zone in enumerate(self.zones):
            if zone['kind'] not in PRECIOUS:
                continue
            cells = self.owner == zid
            if not cells.any():
                continue
            to_cradle = {}
            for t, s in ((self.t1[cells], self.s1[cells]), (self.t2[cells], self.s2[cells])):
                for c in np.unique(s[s >= 0]).tolist():
                    to_cradle[c] = min(to_cradle.get(c, math.inf), float(t[s == c].min()))
            d1, d2 = (sorted(to_cradle.values()) + [math.inf, math.inf])[:2]
            label = ZONES[zone['kind']]['label']
            if d1 >= FAR:
                self.precious.append((label, 'loin', d1, d2))
            elif d2 - d1 <= SHARED + 0.25 * d1:
                self.precious.append((label, 'partagée', d1, d2))
            else:
                self.downgraded.append(label)
                zone['kind'] = 'marche' if d1 < 40 else 'plaine'

    ####################################################################################################################
    # SYSTEMS

    def place_systems(self):
        g = nprng(self.key, 'systems')
        kinds = self.zone_kinds()
        density = np.array([ZONES[k]['density'] for k in kinds])[self.owner]
        amplitude = np.array([ZONES[k]['noise'] for k in kinds])[self.owner]
        r = rng(self.key, 'centres')
        for zid, zone in enumerate(self.zones):
            if zone['kind'] not in ('amas_dense', 'amas_globulaire', 'coeur_noir', 'carrefour'):
                continue
            inside = self.owner == zid
            d = self.dist(zone['y'], zone['x'])[inside]
            if zone['kind'] in ('amas_dense', 'amas_globulaire'):
                sigma = 0.45 * ZONES[zone['kind']]['cap']
                density[inside] *= 0.5 + 2.5 * np.exp(-d ** 2 / (2 * sigma ** 2))
            elif zone['kind'] == 'coeur_noir':
                density[inside] *= np.where(d < 15, 0.05, 0.3 + 2.0 * np.exp(-(d - 32) ** 2 / (2 * 9 ** 2)))
                self.forced.append((zone['y'], zone['x'], 'black_hole', 'coeur_noir'))
            else:
                for star in ('supergiant', 'O', 'B'):
                    self.forced.append((zone['y'] + r.uniform(-12, 12), zone['x'] + r.uniform(-12, 12), star, 'carrefour'))
        halo = ~self.core
        density[halo] *= np.clip(1 - self.halo_dist[halo] / HALO_WIDTH, 0, 1) ** 2
        # Filaments and voids in the open zones, as the cosmic web : ridges of a smooth noise
        ridges = 1 - np.abs(2 * value_noise(g, (self.gh, self.gw), [(10, 0.6), (28, 1.0)]) - 1)
        web = np.isin(kinds[self.owner], list(WEB))
        density[web] *= 0.3 + 1.4 * ridges[web] ** 2
        density = box_blur(density)  # Soft borders between zones

        # Zones at the scale of the unit, through a smooth warp : their borders wave instead of following the cells.
        # The rifts keep their exact band : a warp must never bring two systems closer across a rift.
        rows, cols = np.arange(self.H)[:, None], np.arange(self.W)[None, :]
        wy = (2 * value_noise(g, (self.H, self.W), [(12, 1.0)]) - 1) * WARP
        wx = (2 * value_noise(g, (self.H, self.W), [(12, 1.0)]) - 1) * WARP
        iy = np.clip(((rows + wy) // CELL).astype(np.int32), 0, self.gh - 1)
        ix = np.clip(((cols + wx) // CELL).astype(np.int32), 0, self.gw - 1)
        del wy, wx
        self.owner_u = self.owner[iy, ix]
        exact = np.zeros((self.H, self.W), bool)
        for zid, points, widths in self.rifts:
            for (y, x), w in zip(points, widths):
                radius = w / 2 + 3
                y0, y1 = max(int(y - radius), 0), min(int(y + radius) + 2, self.H)
                x0, x1 = max(int(x - radius), 0), min(int(x + radius) + 2, self.W)
                disc = (rows[y0:y1] - y) ** 2 + (cols[:, x0:x1] - x) ** 2 <= radius * radius
                exact[y0:y1, x0:x1] |= disc
                self.owner_u[y0:y1, x0:x1][disc] = zid
        units = density[iy, ix] * (1 + amplitude[iy, ix] * 0.6 * (2 * value_noise(g, (self.H, self.W), [(6, 0.6), (25, 1.0)]) - 1))
        del iy, ix
        units[np.isin(kinds[self.owner_u], ('faille', 'route')) | exact] = 0
        chance = np.minimum(units * (DENSITY * self.core_area / units.sum()), 0.6)
        del units
        ys, xs = np.nonzero(g.random((self.H, self.W), dtype=np.float32) < chance)

        # Star class and system type, depending on the zone
        system_kinds = kinds[self.owner_u[ys, xs]]
        base = np.array([STARS[c][0] for c in CLASSES])
        type_base = np.array(list(SYSTEM_TYPES.values()) + [0, 0])
        cls, stype = np.zeros(len(ys), np.int64), np.zeros(len(ys), np.int64)
        for kind_name in np.unique(system_kinds):
            sel = system_kinds == kind_name
            w = base * np.array([ZONES[kind_name]['stars'].get(c, 1.0) for c in CLASSES])
            cls[sel] = g.choice(len(CLASSES), size=int(sel.sum()), p=w / w.sum())
            w = type_base * np.array([ZONES[kind_name]['types'].get(t, 1.0) for t in TYPES])
            stype[sel] = g.choice(len(TYPES), size=int(sel.sum()), p=w / w.sum())
        bank = (self.rift_dist[ys // CELL, xs // CELL] <= BANK) & BIG_IDX[cls]
        small = base * ~BIG_IDX
        cls[bank] = g.choice(len(CLASSES), size=int(bank.sum()), p=small / small.sum())

        self.ys, self.xs, self.cls, self.stype = ys.astype(np.int64), xs.astype(np.int64), cls, stype
        self.role = np.array([''] * len(ys), dtype=object)
        at = {(y, x): i for i, (y, x) in enumerate(zip(ys.tolist(), xs.tolist()))}
        self.forced_index = []
        for y, x, star, why in self.forced:
            y, x = min(max(int(round(y)), 0), self.H - 1), min(max(int(round(x)), 0), self.W - 1)
            i = at.get((y, x))
            if i is None:
                i = at[(y, x)] = self.add_system(y, x, star, why)
            self.cls[i], self.role[i] = CLASSES.index(star), why
            self.forced_index.append(i)

    def add_system(self, y, x, star, why):
        self.ys, self.xs = np.append(self.ys, int(y)), np.append(self.xs, int(x))
        self.cls, self.stype = np.append(self.cls, CLASSES.index(star)), np.append(self.stype, T['standard'])
        self.role = np.append(self.role, np.array([why], dtype=object))
        return len(self.ys) - 1

    @property
    def n(self):
        return len(self.ys)

    def system_zones(self):
        return self.owner_u[self.ys, self.xs]

    def around(self, h, radius):
        # The systems within radius of system h, and their distances
        near = np.flatnonzero((np.abs(self.ys - self.ys[h]) <= radius) & (np.abs(self.xs - self.xs[h]) <= radius))
        d = np.hypot(self.ys[near] - self.ys[h], self.xs[near] - self.xs[h])
        return near[d <= radius], d[d <= radius]

    def place_homes(self):
        r = rng(self.key, 'homes')
        self.homes = np.array([i for i, (_, _, _, why) in zip(self.forced_index, self.forced) if why == 'monde_natal'], np.int64)
        self.stype[self.homes] = T['native']

        zone_of = self.system_zones()
        vestiges = [i for i, zone in enumerate(self.zones) if zone['kind'] == 'vestiges']
        if vestiges:
            zone = self.zones[vestiges[0]]
            inside = np.flatnonzero(zone_of == vestiges[0])
            if len(inside):
                i = inside[np.argmin(np.hypot(self.ys[inside] - zone['y'], self.xs[inside] - zone['x']))]
                self.stype[i], self.role[i] = T['vestige'], 'vestige'

        # The kit : a floor and a ceiling around each home, the same start for everyone whatever the luck of the draw
        big_choices = [CLASSES.index(c) for c in ('A', 'B', 'giant', 'O')]
        local = {h: self.around(h, 30) for h in self.homes.tolist()}
        for _ in range(4):
            for h in r.sample(self.homes.tolist(), len(self.homes)):
                near, d = local[h]
                for what, inner, outer, least, most in KIT:
                    ring = near[(d >= inner) & (d <= outer)]
                    has = ring[BIG_IDX[self.cls[ring]] if what == 'big' else self.stype[ring] == T[what]]
                    movable = ring[(self.role[ring] == '') & (self.stype[ring] == T['standard'])]
                    if len(has) < least:
                        pool = movable[~BIG_IDX[self.cls[movable]]] if what == 'big' else movable
                        for i in r.sample(pool.tolist(), min(least - len(has), len(pool))):
                            if what == 'big':
                                self.cls[i] = r.choice(big_choices)
                            else:
                                self.stype[i] = T[what]
                    elif len(has) > most:
                        extra = has[self.role[has] == ''].tolist()
                        for i in r.sample(extra, min(len(has) - most, len(extra))):
                            if what == 'big':
                                self.cls[i] = CLASSES.index(r.choice(('K', 'M')))
                            else:
                                self.stype[i] = T['standard']

    ####################################################################################################################
    # CONNECTIVITY

    def link(self):
        # Two systems are linked when the bigger of their two stars reaches the other one
        size = int(RANGE.max()) + 1
        reach = RANGE[self.cls]
        key = (self.ys // size) * 100_000 + self.xs // size
        order = np.argsort(key, kind='stable')
        keys, starts = np.unique(key[order], return_index=True)
        ends = list(starts[1:]) + [len(order)]
        buckets = {int(k): order[s:e] for k, s, e in zip(keys, starts, ends)}
        edges = []
        for k, a in buckets.items():
            for offset in (0, 1, 100_000 - 1, 100_000, 100_000 + 1):
                b = buckets.get(k + offset)
                if b is None:
                    continue
                d2 = (self.ys[a, None] - self.ys[None, b]) ** 2 + (self.xs[a, None] - self.xs[None, b]) ** 2
                linked = d2 <= np.maximum(reach[a, None], reach[None, b]) ** 2
                if offset == 0:
                    linked = np.triu(linked, 1)
                i, j = np.nonzero(linked)
                edges.append(np.stack([a[i], b[j]], 1))
        self.edges = np.concatenate(edges)

        parent = list(range(self.n))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for a, b in self.edges.tolist():
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
        self.comp = np.array([find(i) for i in range(self.n)])
        self.main = int(np.argmax(np.bincount(self.comp)))

    def repair(self):
        # No technology lengthens a vortex : a region left apart would stay unreachable forever. Connect the ones that matter.
        self.repairs = []
        for _ in range(6):
            self.link()
            sizes = np.bincount(self.comp, minlength=self.n)
            with_home = set(self.comp[self.homes].tolist())
            todo = [c for c in np.flatnonzero(sizes).tolist() if c != self.main and (sizes[c] >= 25 or c in with_home)]
            if not todo:
                return
            main = np.flatnonzero(self.comp == self.main)
            for c in todo:
                inside = np.flatnonzero(self.comp == c)
                best = (math.inf, 0, 0)
                for chunk in np.array_split(inside, max(1, len(inside) // 200)):
                    d2 = (self.ys[chunk, None] - self.ys[None, main]) ** 2 + (self.xs[chunk, None] - self.xs[None, main]) ** 2
                    i, j = divmod(int(np.argmin(d2)), len(main))
                    if d2[i, j] < best[0]:
                        best = (float(d2[i, j]), int(chunk[i]), int(main[j]))
                gap, a, b = math.sqrt(best[0]), best[1], best[2]
                if gap <= STARS['supergiant'][1]:
                    star = min((c for c in ('A', 'B', 'giant', 'O', 'wolf_rayet', 'supergiant') if STARS[c][1] >= gap), key=lambda c: STARS[c][1])
                    self.cls[a], self.role[a] = CLASSES.index(star), 'reparation'
                else:
                    steps = int(gap // 22) + 1
                    for s in range(1, steps):
                        y = self.ys[a] + (self.ys[b] - self.ys[a]) * s / steps
                        x = self.xs[a] + (self.xs[b] - self.xs[a]) * s / steps
                        self.add_system(round(y), round(x), 'supergiant', 'reparation')
                self.repairs.append((int(sizes[c]), round(gap, 1)))
        self.link()

    def corridors(self, is_source, is_sink, size=20):
        # How many paths go from the sources to the sinks without sharing a square of size x size units
        width = self.W // size + 1
        cells = (self.ys // size) * width + self.xs // size
        main = self.comp == self.main
        nodes = {c: v for v, c in enumerate(np.unique(cells[main]).tolist())}
        a, b = self.edges[:, 0], self.edges[:, 1]
        keep = main[a] & (cells[a] != cells[b])
        pairs = np.unique(np.sort(np.stack([cells[a][keep], cells[b][keep]], 1), axis=1), axis=0).tolist() if keep.any() else []
        n = len(nodes)
        s, t = 2 * n, 2 * n + 1
        arcs = []
        for c, v in nodes.items():
            y, x = (c // width + 0.5) * size, (c % width + 0.5) * size
            source, sink = is_source(y, x), is_sink(y, x)
            arcs.append((2 * v, 2 * v + 1, INF if source or sink else 1))
            if source:
                arcs.append((s, 2 * v, INF))
            if sink:
                arcs.append((2 * v + 1, t, INF))
        for c1, c2 in pairs:
            u, v = nodes[c1], nodes[c2]
            arcs += [(2 * u + 1, 2 * v, INF), (2 * v + 1, 2 * u, INF)]
        flow, reached = max_flow(2 * n + 2, arcs, s, t)
        cut = [((c // width) * size, (c % width) * size) for c, v in nodes.items() if reached[2 * v] and not reached[2 * v + 1]]
        return flow, cut, size

    def path_lengths(self, source):
        if not hasattr(self, 'adjacency'):
            both = np.concatenate([self.edges, self.edges[:, ::-1]])
            both = both[np.argsort(both[:, 0], kind='stable')]
            weights = np.hypot(self.ys[both[:, 0]] - self.ys[both[:, 1]], self.xs[both[:, 0]] - self.xs[both[:, 1]])
            self.adjacency = (np.searchsorted(both[:, 0], np.arange(self.n + 1)).tolist(), both[:, 1].tolist(), weights.tolist())
        starts, neighbours, weights = self.adjacency
        dist = [math.inf] * self.n
        dist[source] = 0.0
        heap = [(0.0, source)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            for k in range(starts[u], starts[u + 1]):
                v, nd = neighbours[k], d + weights[k]
                if nd < dist[v]:
                    dist[v] = nd
                    heapq.heappush(heap, (nd, v))
        return dist

    def measure(self):
        m = self.measures = {}
        y0, y1, x0, x1 = self.box
        west, east = x0 + 0.12 * (x1 - x0), x1 - 0.12 * (x1 - x0)
        north, south = y0 + 0.12 * (y1 - y0), y1 - 0.12 * (y1 - y0)
        m['ouest_est'] = self.corridors(lambda y, x: x < west, lambda y, x: x > east)
        m['nord_sud'] = self.corridors(lambda y, x: y < north, lambda y, x: y > south)
        treasure = np.flatnonzero(self.role == 'vestige').tolist()
        m['vestiges'] = None
        if treasure:  # Every route that reaches the surroundings of the vestiges
            ty, tx = self.ys[treasure[0]], self.xs[treasure[0]]
            m['vestiges'] = self.corridors(lambda y, x: x < west, lambda y, x: math.hypot(y - ty, x - tx) <= 80)

        # Equity around each home
        rows = []
        for h in self.homes.tolist():
            near, d = self.around(h, 30)
            row = {'systèmes à 25 u': int((d <= 25).sum()) - 1}
            for what, inner, outer, least, most in KIT[:4]:  # The same rings as the kit
                has = BIG_IDX[self.cls[near]] if what == 'big' else self.stype[near] == T[what]
                row[f'{"grandes étoiles" if what == "big" else what} de {inner} à {outer} u'] = int(((d >= inner) & (d <= outer) & has).sum())
            others = np.hypot(self.ys[self.homes] - self.ys[h], self.xs[self.homes] - self.xs[h])
            row['monde natal le plus proche'] = round(float(np.min(others[others > 0])), 1) if len(self.homes) > 1 else 0
            # The widest free angle around the home, among the other homes within 60 u : no home is surrounded
            close = (others > 0) & (others <= 60)
            angles = sorted(np.degrees(np.arctan2(self.ys[self.homes][close] - self.ys[h], self.xs[self.homes][close] - self.xs[h])).tolist())
            gaps = [b - a for a, b in zip(angles, angles[1:] + [angles[0] + 360])] if angles else [360]
            row['angle libre (°)'] = round(max(gaps))
            counts = list(row.values())
            row['score'] = round(1.5 * counts[1] + 2 * counts[2] + counts[3] + 3 * counts[4] + counts[0] / 30, 1)
            rows.append(row)
        m['equity'] = rows

        # Detour between cradles : length of the vortex path / straight line
        firsts = [h for k, h in enumerate(self.homes.tolist()) if k == 0 or self.home_cradle[k] != self.home_cradle[k - 1]]
        ratios = []
        for k, source in enumerate(firsts[:6]):
            dist = self.path_lengths(source)
            for target in firsts[k + 1:]:
                ratios.append(round(dist[target] / math.hypot(self.ys[source] - self.ys[target], self.xs[source] - self.xs[target]), 2))
        m['detours'] = ratios


########################################################################################################################
# PICTURES AND REPORT


def font(size, bold=False):
    try:
        return ImageFont.truetype('arialbd.ttf' if bold else 'arial.ttf', size)
    except OSError:
        return ImageFont.load_default()


def render(sector, folder):
    scale = min(2.0, 2400 / max(sector.W, sector.H))
    ui = 1.0  # Size of the texts and markers : the same on every map, still readable on the large ones
    width, height = round(sector.W * scale), round(sector.H * scale)
    dot = max(1, round(scale))
    px = np.minimum((sector.xs * scale).astype(int), width - dot)
    py = np.minimum((sector.ys * scale).astype(int), height - dot)

    def dots(img, sel, colours):
        for dy in range(dot):
            for dx in range(dot):
                img[py[sel] + dy, px[sel] + dx] = colours

    # 1. Blank : only the systems, as on today's map
    blank = np.zeros((height, width, 3), np.uint8)
    bright = nprng(sector.key, 'render').integers(70, 241, sector.n).astype(np.uint8)
    dots(blank, np.ones(sector.n, bool), np.repeat(bright[:, None], 3, 1))
    Image.fromarray(blank).save(os.path.join(folder, f'{sector.key}_vierge.png'))

    # 2. Zones, stars, homes and bottlenecks
    colour = np.array([ZONES[zone['kind']]['colour'] for zone in sector.zones], np.float32)
    owner = np.asarray(Image.fromarray(sector.owner_u).resize((width, height), Image.NEAREST))
    img = colour[owner] * 0.28
    border = np.zeros((height, width), bool)
    border[:, 1:] |= owner[:, 1:] != owner[:, :-1]
    border[1:] |= owner[1:] != owner[:-1]
    img[border] = colour[owner[border]] * 0.75
    img = img.astype(np.uint8)
    rgb = (np.array([STARS[c][2] for c in CLASSES], np.float32)[sector.cls] * 0.8).astype(np.uint8)
    rgb[sector.comp != sector.main] = (150, 45, 45)
    small = ~BIG_IDX[sector.cls]
    dots(img, small, rgb[small])

    panel = round(480 * ui)
    canvas = Image.new('RGB', (width + panel, height), (0, 0, 0))
    canvas.paste(Image.fromarray(img), (0, 0))
    draw = ImageDraw.Draw(canvas)

    for (y1, x1), (y2, x2) in sector.bridges:
        draw.line([(x1 * scale, y1 * scale), (x2 * scale, y2 * scale)], fill=(255, 235, 160), width=2)
    for i in np.flatnonzero(~small).tolist():
        star = CLASSES[sector.cls[i]]
        r = (0.8 + 0.8 * STARS[star][3]) * scale * 0.75
        x, y = sector.xs[i] * scale + dot / 2, sector.ys[i] * scale + dot / 2
        if star == 'black_hole':
            draw.ellipse([x - r - 2, y - r - 2, x + r + 2, y + r + 2], fill=(0, 0, 0), outline=(255, 255, 255), width=2)
        else:
            draw.ellipse([x - r, y - r, x + r, y + r], fill=STARS[star][2])
    for i in np.flatnonzero(sector.role == 'reparation').tolist():
        x, y = sector.xs[i] * scale, sector.ys[i] * scale
        draw.ellipse([x - 9 * ui, y - 9 * ui, x + 9 * ui, y + 9 * ui], outline=(255, 0, 255), width=2)
    for h in sector.homes.tolist():
        x, y = sector.xs[h] * scale + dot / 2, sector.ys[h] * scale + dot / 2
        draw.ellipse([x - 7 * ui, y - 7 * ui, x + 7 * ui, y + 7 * ui], outline=(90, 255, 150), width=2)
        draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(255, 255, 255))
    for i in np.flatnonzero(sector.role == 'vestige').tolist():
        x, y = sector.xs[i] * scale, sector.ys[i] * scale
        draw.polygon([(x, y - 12 * ui), (x + 9 * ui, y), (x, y + 12 * ui), (x - 9 * ui, y)], fill=(255, 215, 0), outline=(0, 0, 0))

    # The bottlenecks : the squares of the minimum cut, when it is narrow
    for name, colour_cut in (('vestiges', (255, 215, 0)), ('ouest_est', (255, 60, 60)), ('nord_sud', (255, 60, 60))):
        result = sector.measures.get(name)
        if result and result[0] <= 6:
            flow, cut, size = result
            for y, x in cut:
                draw.rectangle([x * scale, y * scale, (x + size) * scale, (y + size) * scale], outline=colour_cut, width=2)

    # Labels at the point of each zone the farthest from its borders
    edge = np.zeros(sector.owner.shape, bool)
    edge[[0, -1], :] = edge[:, [0, -1]] = True
    edge[:, 1:] |= sector.owner[:, 1:] != sector.owner[:, :-1]
    edge[:, :-1] |= sector.owner[:, :-1] != sector.owner[:, 1:]
    edge[1:] |= sector.owner[1:] != sector.owner[:-1]
    edge[:-1] |= sector.owner[:-1] != sector.owner[1:]
    inner = np.zeros(sector.owner.shape, np.int32)
    inside = ~edge
    depth = 0
    while inside.any():
        depth += 1
        inner[inside] = depth
        inside &= ~dilate(~inside)
    sizes = np.bincount(sector.owner.ravel(), minlength=len(sector.zones))
    for zid, zone in enumerate(sector.zones):
        if not sizes[zid]:
            continue
        i, j = divmod(int(np.argmax(np.where(sector.owner == zid, inner, -1))), sector.gw)
        spec = ZONES[zone['kind']]
        size = int(np.clip(11 + math.sqrt(sizes[zid]) * CELL / 16, 13, 30) * ui)
        light = tuple(int(c * 0.55 + 255 * 0.45) for c in spec['colour'])
        draw.text((sector.cx[j] * scale, sector.cy[i] * scale), spec['label'], fill=light, font=font(size, True),
                  anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))

    # Legend
    x0, y = width + 24 * ui, 24 * ui
    big_font, text_font, line = font(int(24 * ui), True), font(int(15 * ui)), 21 * ui
    m = sector.measures
    draw.text((x0, y), f'{sector.key} · {sector.players} joueurs', fill=(255, 255, 255), font=big_font)
    y += 40 * ui
    for text in (f'{sector.W} × {sector.H} unités · {sector.n:,} systèmes'.replace(',', ' '),
                 f'{len(sector.homes)} mondes natals · {int((sizes > 0).sum())} zones',
                 f'Couloirs ouest↔est : {m["ouest_est"][0]} · nord↔sud : {m["nord_sud"][0]}',
                 f'Couloirs vers les vestiges : {m["vestiges"][0] if m["vestiges"] else "-"}'):
        draw.text((x0, y), text, fill=(200, 200, 200), font=text_font)
        y += line
    y += line / 2
    present = {zone['kind'] for zid, zone in enumerate(sector.zones) if sizes[zid]}
    for kind_name, spec in ZONES.items():
        if kind_name in present:
            draw.rectangle([x0, y + 3, x0 + 26 * ui, y + 17 * ui], fill=tuple(int(c * 0.6) for c in spec['colour']), outline=spec['colour'])
            draw.text((x0 + 36 * ui, y), spec['label'], fill=(220, 220, 220), font=text_font)
            y += line
    y += line / 2
    draw.text((x0, y), 'Grandes étoiles (portée des vortex)', fill=(255, 255, 255), font=text_font)
    y += line
    for star in ('A', 'B', 'giant', 'O', 'wolf_rayet', 'supergiant', 'black_hole'):
        r = (0.8 + 0.8 * STARS[star][3]) * max(scale, 1.4) * 0.75
        cx, cy = x0 + 13 * ui, y + 9 * ui
        if star == 'black_hole':
            draw.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], fill=(0, 0, 0), outline=(255, 255, 255), width=2)
        else:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=STARS[star][2])
        draw.text((x0 + 36 * ui, y), f'{STAR_NAMES[star]} : {STARS[star][1]} u', fill=(220, 220, 220), font=text_font)
        y += line
    draw.text((x0, y), 'Petites étoiles : 5 à 9 u', fill=(220, 220, 220), font=text_font)
    y += line * 1.5
    for marker, text in (('home', 'Monde natal'), ('bridge', 'Vortex prévu (tête de pont, route)'),
                         ('repair', 'Étoile ajoutée ou agrandie (réparation)'),
                         ('vestige', 'Vestiges (mode chasse au trésor)'), ('cut', 'Goulot (6 couloirs ou moins)'),
                         ('island', 'Système isolé, inaccessible')):
        cx, cy = x0 + 13 * ui, y + 9 * ui
        if marker == 'home':
            draw.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], outline=(90, 255, 150), width=2)
        elif marker == 'bridge':
            draw.line([(cx - 10, cy), (cx + 10, cy)], fill=(255, 235, 160), width=2)
        elif marker == 'repair':
            draw.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], outline=(255, 0, 255), width=2)
        elif marker == 'vestige':
            draw.polygon([(cx, cy - 10), (cx + 8, cy), (cx, cy + 10), (cx - 8, cy)], fill=(255, 215, 0))
        elif marker == 'cut':
            draw.rectangle([cx - 8, cy - 8, cx + 8, cy + 8], outline=(255, 60, 60), width=2)
        else:
            draw.rectangle([cx - 2, cy - 2, cx + 2, cy + 2], fill=(150, 45, 45))
        draw.text((x0 + 36 * ui, y), text, fill=(220, 220, 220), font=text_font)
        y += line
    canvas.save(os.path.join(folder, f'{sector.key}_zones.png'))


def report(sector, folder):
    m, zone_of = sector.measures, sector.system_zones()
    sizes = np.bincount(sector.owner_u.ravel(), minlength=len(sector.zones))
    lines = [f'Génération « {sector.key} » : {sector.players} joueurs, toile de {sector.W} × {sector.H} unités, '
             f'galaxie de {sector.core_area / 1e6:.2f} million d\'unités² (agrandie de {sector.grown - 1:.0%} pour loger les berceaux)',
             'Durées : ' + ', '.join(f'{name} {seconds:.1f} s' for name, seconds in sector.timings.items()), '',
             f'Systèmes : {sector.n} (densité moyenne dans la galaxie {sector.n / sector.core_area:.3f} / u²)', '', 'Zones :']
    for kind_name, spec in ZONES.items():
        ids = [zid for zid, zone in enumerate(sector.zones) if zone['kind'] == kind_name and sizes[zid]]
        if ids:
            count = int(np.isin(zone_of, ids).sum())
            share = '' if kind_name == 'halo' else f'{sizes[ids].sum() / sector.core_area:6.1%} de la galaxie'
            lines.append(f'  {spec["label"]:<24} {len(ids):>3} zone(s)  {count:>6} systèmes  {share}')
    shares = Counter(CLASSES[c] for c in sector.cls.tolist())
    big = sum(v for c, v in shares.items() if c in BIG)
    lines += ['', f'Étoiles : {big / sector.n:.1%} de grandes étoiles (' +
              ', '.join(f'{STAR_NAMES[c]} {shares[c] / sector.n:.2%}' for c in STAR_NAMES if shares[c]) + ')']

    rows = m['equity']
    scores = [row['score'] for row in rows]
    lines += ['', f'Équité, autour de chacun des {len(rows)} mondes natals ({sector.n_cradles} berceaux) :']
    for name in rows[0] if rows else ():
        lines.append(f'  {name:<30} {stats([row[name] for row in rows])}')
    if scores:
        lines.append(f'  écart du score : le meilleur a {max(scores) / min(scores):.2f} fois le score du plus faible')
    lines.append(f'  distance des berceaux au halo : {float(sector.depth[sector.cradle_mask].min()):g} u au plus près')
    lines.append(f'  zones précieuses : {sum(1 for p in sector.precious if p[1] == "loin")} loin de tout berceau, '
                 f'{sum(1 for p in sector.precious if p[1] == "partagée")} partagées entre deux berceaux, '
                 f'{len(sector.downgraded)} rendues ordinaires car trop près d\'un seul ' + ' '.join(f'({label})' for label in sector.downgraded))
    for label, why, d1, d2 in sector.precious:
        lines.append(f'    {label:<22} {why:<9} trajet depuis le berceau le plus proche {d1:5.0f} u, depuis le deuxième {d2:5.0f} u')

    sizes_comp = np.bincount(sector.comp)
    lines += ['', 'Connectivité (lien vortex si la distance ≤ portée de la plus grande des deux étoiles) :',
              f'  liens : {len(sector.edges)} ; réseau principal : {sizes_comp[sector.main] / sector.n:.1%} des systèmes',
              f'  mondes natals dans le réseau principal : {int((sector.comp[sector.homes] == sector.main).sum())} / {len(sector.homes)}',
              f'  systèmes isolés, inaccessibles : {int((sector.comp != sector.main).sum())} en {len(set(sector.comp.tolist())) - 1} îlots, '
              f'dont {int(((sector.comp != sector.main) & sector.core[sector.ys // CELL, sector.xs // CELL]).sum())} dans la galaxie (les autres dans le halo)',
              f'  têtes de pont : {len(sector.bridge_points)} placées, {sector.skipped_bridgeheads} abandonnées faute de deux vraies régions à relier',
              f'  réparations : {len(sector.repairs)} ' + ' '.join(f'(îlot de {s} systèmes à {g} u)' for s, g in sector.repairs),
              f'  couloirs indépendants (carrés de 20 u) ouest↔est : {m["ouest_est"][0]}, nord↔sud : {m["nord_sud"][0]}',
              f'  mode chasse au trésor, du bord ouest aux vestiges : {m["vestiges"][0] if m["vestiges"] else "pas de vestiges"} couloirs',
              f'  détour entre berceaux (chemin par vortex / ligne droite) : {stats(m["detours"])}']

    lines += ['', 'Identifiants lisibles (y.x-orbite) comparés aux identifiants actuels :']
    for h in sector.homes[:3].tolist():
        y, x = int(sector.ys[h]), int(sector.xs[h])
        lines.append(f'  {y:04}.{x:04}-3   au lieu de   1000{y // 100:03}{x // 100:03}{y % 100:03}{x % 100:03}03')
    with open(os.path.join(folder, f'{sector.key}_rapport.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def generate(key, players):
    start = time.perf_counter()
    grow = 1.0
    while True:
        sector = Sector(key, players, grow)
        try:
            sector.layout()
            break
        except Crowded:
            grow *= 1.05
    sector.grown = grow
    sector.place_systems()
    sector.place_homes()
    sector.timings['génération'] = time.perf_counter() - start
    start = time.perf_counter()
    sector.repair()
    sector.measure()
    sector.timings['contrôles'] = time.perf_counter() - start
    return sector


def summary_line(sector):
    m, rows = sector.measures, sector.measures['equity']
    scores, detours = [row['score'] for row in rows], sorted(m['detours'])
    return (f'{sector.key:<10} {sector.W:>5}  {sector.n:>7}  {int((np.bincount(sector.owner_u.ravel()) > 0).sum()):>5}'
            f'  {max(scores) / min(scores):>6.2f}  {min(row["angle libre (°)"] for row in rows):>6}'
            f'  {float(sector.depth[sector.cradle_mask].min()):>5g}  {np.mean(sector.comp == sector.main):>6.1%}'
            f'  {len(sector.bridge_points):>3}/{sector.skipped_bridgeheads:<2}  {len(sector.downgraded):>5}  {len(sector.repairs):>5}'
            f'  {m["ouest_est"][0]:>3}  {m["nord_sud"][0]:>3}  {m["vestiges"][0] if m["vestiges"] else "-":>6}'
            f'  {detours[len(detours) // 2] if detours else "-":>6}  {sum(sector.timings.values()):>5.1f} s')


SUMMARY_TITLE = ('carte      toile  systèm.  zones  équité  angle  halo  réseau  ponts/ab.  préc.  répar.  O↔E  N↔S  trésor  détour  durée\n'
                 '                                   (max/min)  libre  (u)          placées/  dégr.\n'
                 '                                                                    abandon.')


def check():
    global SECRET
    a, b = generate('controle', 20), generate('controle', 20)
    assert np.array_equal(a.owner, b.owner) and np.array_equal(a.ys, b.ys) and np.array_equal(a.cls, b.cls), 'Not deterministic'
    SECRET += '-autre'
    c = generate('controle', 20)
    assert not (np.array_equal(a.ys, c.ys) if len(a.ys) == len(c.ys) else False), 'Another secret must give another map'
    assert (a.comp[a.homes] == a.main).all(), 'A home is out of the main network'
    assert min(row['angle libre (°)'] for row in a.measures['equity']) >= 180, 'A home is surrounded by the others'
    print('OK : same secret, same map ; another secret, another map ; every home is reachable and none is surrounded')


def main():
    sys.stdout.reconfigure(encoding='utf-8')  # The Windows console would choke on the accents
    if '--check' in sys.argv:
        return check()
    if len(sys.argv) == 3:
        batches, single = [(int(sys.argv[2]), 1)], sys.argv[1]
    else:
        batches, single = [b for b in BATCHES if len(sys.argv) == 1 or b[0] == int(sys.argv[1])], None
    # Every run in a new folder "gen N", after the ones already there
    os.makedirs(OUT, exist_ok=True)
    done = [int(name[4:]) for name in os.listdir(OUT) if name.startswith('gen ') and name[4:].isdigit()]
    folder = os.path.join(OUT, f'gen {max(done, default=0) + 1}')
    os.makedirs(folder)
    print(folder, flush=True)
    summary = []
    for players, count in batches:
        lines = [f'{count} carte(s) pour {players} joueurs', SUMMARY_TITLE]
        for k in range(1, count + 1):
            sector = generate(single or f'{players}j-{k:02}', players)
            start = time.perf_counter()
            render(sector, folder)
            report(sector, folder)
            sector.timings['images'] = time.perf_counter() - start
            lines.append(summary_line(sector))
            print(lines[-1], flush=True)
        summary.append('\n'.join(lines))
    with open(os.path.join(folder, 'resume.txt'), 'w', encoding='utf-8') as f:
        f.write('\n\n'.join(summary) + '\n')


if __name__ == '__main__':
    main()
