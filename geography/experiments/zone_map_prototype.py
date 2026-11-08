"""
Prototype : a sector without tiles nor quadrants, cut into natural zones.

Standalone experiment, numpy + Pillow only (no Django, no database) :
    python geography/experiments/zone_map_prototype.py                several generations
    python geography/experiments/zone_map_prototype.py key 1000 1000  one generation
    python geography/experiments/zone_map_prototype.py --check        determinism self-check
For each generation, geography/experiments/output/ receives <key>_vierge.png (the systems only), <key>_zones.png
(zones, stars, homes, bottlenecks) and <key>_rapport.txt (equity, connectivity, timings).

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

CELL = 5                # Size of a zone cell, in units
DENSITY = 0.04          # Systems per unit², as today : 40 591 systems on 1000 x 1000
HOMES_PER_CRADLE = 10
CRADLE_RADIUS = 100
HOME_SPACING = 24
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
    'halo': kind('Halo', (75, 75, 95), 0.35),
    'vestiges': kind('Vestiges', (255, 215, 0), 0.6, 0.6, 30, types={'scientific': 5}),
}
STAMPED = {'halo', 'berceau', 'faille', 'tete_de_pont', 'abime', 'route'}  # Drawn with their shape, the others grow
FREE_ZONES = {'plaine': 22, 'sauvage': 10, 'debris': 8, 'gazier': 8, 'nebuleuse_sombre': 8, 'amas_globulaire': 8,
              'pouponniere': 6, 'anomalies': 5, 'supernova': 4}
DANGEROUS = {'supernova', 'anomalies', 'nebuleuse_sombre'}  # Never next to a cradle
WEB = {'plaine', 'marche', 'sauvage', 'gazier', 'debris', 'nebuleuse_sombre', 'pouponniere', 'anomalies', 'supernova'}  # Filaments and voids

# What every home finds around it : (system type or 'big' for a big star, from, to (units), at least, at most)
# The habitable worlds of the kit stay within half the spacing of the homes : nobody shares them, the floors and ceilings never fight.
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


########################################################################################################################
# THE SECTOR


class Sector:

    def __init__(self, key, width, height):
        self.key, self.W, self.H = key, width, height
        self.gh, self.gw = height // CELL, width // CELL
        self.cy = (np.arange(self.gh) + 0.5) * CELL
        self.cx = (np.arange(self.gw) + 0.5) * CELL
        self.owner = np.full((self.gh, self.gw), -1, np.int32)
        self.zones = []
        self.forced = []  # (y, x, star class, role) : the stars placed on purpose
        self.bridges = []  # ((y, x), (y, x)) : the vortex planned across a rift or an abyss
        self.timings = {}

    def dist(self, y, x):
        return np.hypot(self.cy[:, None] - y, self.cx[None, :] - x)

    def cell(self, y, x):
        return min(max(int(y // CELL), 0), self.gh - 1), min(max(int(x // CELL), 0), self.gw - 1)

    def add_zone(self, kind_name, y, x):
        self.zones.append({'kind': kind_name, 'y': float(y), 'x': float(x)})
        return len(self.zones) - 1

    def zone_kinds(self):
        return np.array([zone['kind'] for zone in self.zones])

    ####################################################################################################################
    # ZONES

    def layout(self):
        g = nprng(self.key, 'layout')
        self.edge = np.minimum(np.minimum(self.cy[:, None], self.H - self.cy[:, None]),
                               np.minimum(self.cx[None, :], self.W - self.cx[None, :]))
        self.halo_width = 20 + 25 * value_noise(g, (self.gh, self.gw), [(12, 1.0)])
        self.owner[self.edge < self.halo_width] = self.add_zone('halo', 0, 0)
        self.place_cradles(g)
        self.place_rifts()
        self.place_abysses()
        self.place_seeds()
        self.grow()

    def place_cradles(self, g):
        r = rng(self.key, 'cradles')
        n = max(1, round(self.W * self.H / 110_000))
        margin = min(150, self.H / 4, self.W / 4)
        spacing = math.sqrt(self.W * self.H / n)
        while True:
            centres = []
            for _ in range(5000):
                p = (r.uniform(margin, self.H - margin), r.uniform(margin, self.W - margin))
                if all(math.dist(p, c) >= spacing for c in centres):
                    centres.append(p)
                    if len(centres) == n:
                        break
            if len(centres) == n:
                break
            spacing *= 0.95
        # Stamped as noisy discs of the same size : every cradle gets the same room
        shape = value_noise(g, (self.gh, self.gw), [(6, 1.0)])
        self.cradles = []
        for y, x in centres:
            zid = self.add_zone('berceau', y, x)
            self.owner[self.dist(y, x) <= CRADLE_RADIUS * (0.85 + 0.3 * shape)] = zid
            self.cradles.append(zid)
        self.cradle_spacing = spacing
        d = np.sort(np.stack([self.dist(y, x) for y, x in centres]), axis=0)
        never = np.full((self.gh, self.gw), np.inf)
        self.d1, self.d2, self.d3 = d[0], d[1] if n > 1 else never, d[2] if n > 2 else never

    def place_rifts(self):
        r = rng(self.key, 'rifts')
        centres = [(self.zones[i]['y'], self.zones[i]['x']) for i in self.cradles]
        avoid = CRADLE_RADIUS + 40

        def blocked(p):
            return not (20 < p[0] < self.H - 20 and 20 < p[1] < self.W - 20) or any(math.dist(p, c) < avoid for c in centres)

        self.rifts = []
        for _ in range(round(self.W * self.H / 200_000)):
            for _ in range(100):
                start = (r.uniform(0.15, 0.85) * self.H, r.uniform(0.15, 0.85) * self.W)
                if min(math.dist(start, c) for c in centres) > avoid + 30:
                    break
            else:
                continue
            heading, half = r.uniform(0, 2 * math.pi), r.uniform(200, 450)
            sides = []
            for turn in (0, math.pi):
                p, h, side = start, heading + turn, []
                while len(side) * 8 < half:
                    h += r.gauss(0, 0.12)
                    # A rift bends around the cradles : it becomes a natural border between them
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
            if len(points) < 15:
                continue
            phase = r.uniform(0, 6.3)
            widths = [12 + 8 * (0.5 + 0.5 * math.sin(phase + k * 0.09)) for k in range(len(points))]
            zid = self.add_zone('faille', *points[len(points) // 2])
            for (y, x), w in zip(points, widths):
                self.owner[self.dist(y, x) <= w / 2 + 3] = zid  # + 3 : no system closer than w across the rift
            self.rifts.append((zid, points, widths))
        self.rift = np.isin(self.owner, [i for i, zone in enumerate(self.zones) if zone['kind'] == 'faille'])
        self.rift_dist = distance_from(self.rift, 12) * CELL
        for _, points, widths in self.rifts:
            self.place_bridgeheads(r, points, widths)

    def place_bridgeheads(self, r, points, widths):
        # A pair of big stars face each other across the rift : the only way to cross it
        n = max(2, round(len(points) * 8 / 170))
        for k in range(n):
            i = int((k + 0.5) / n * (len(points) - 1) + r.uniform(-0.2, 0.2) * len(points) / n)
            i = min(max(i, 1), len(points) - 2)
            (y, x), w = points[i], widths[i]
            ty, tx = points[i + 1][0] - points[i - 1][0], points[i + 1][1] - points[i - 1][1]
            norm = math.hypot(ty, tx)
            ny, nx = tx / norm, -ty / norm
            half = w / 2 + 2
            far = r.choice([c for c in ('giant', 'O', 'wolf_rayet', 'supergiant') if STARS[c][1] >= 2 * half + 1])
            sides = [(y + ny * half, x + nx * half), (y - ny * half, x - nx * half)]
            r.shuffle(sides)
            self.forced.append((*sides[0], far, 'tete_de_pont'))
            self.forced.append((*sides[1], r.choice(('A', 'B', 'giant', 'O')), 'tete_de_pont'))
            self.bridges.append((sides[0], sides[1]))
            zid = self.add_zone('tete_de_pont', y, x)
            self.owner[(self.dist(y, x) <= 20) & ~self.rift & ~np.isin(self.owner, self.cradles)] = zid

    def place_abysses(self):
        r = rng(self.key, 'abysses')
        shape = value_noise(nprng(self.key, 'abysses'), (self.gh, self.gw), [(10, 1.0)])
        for _ in range(round(self.W * self.H / 450_000)):
            for _ in range(300):
                radius = r.uniform(55, 90)
                y, x = r.uniform(radius + 60, self.H - radius - 60), r.uniform(radius + 60, self.W - radius - 60)
                if self.d1[self.cell(y, x)] > CRADLE_RADIUS + radius * 1.25 + 30 and self.owner[self.cell(y, x)] == -1:
                    break
            else:
                continue
            zid = self.add_zone('abime', y, x)
            self.owner[(self.dist(y, x) <= radius * (0.75 + 0.5 * shape)) & (self.owner == -1)] = zid
            if r.random() < 0.6:  # A road of giants crosses it
                angle = r.uniform(0, math.pi)
                dy, dx = math.sin(angle), math.cos(angle)
                reach = radius * 1.25 + 8
                steps = int(2 * reach / 13) + 1
                relays = [(y + (-reach + s * 2 * reach / steps) * dy, x + (-reach + s * 2 * reach / steps) * dx) for s in range(steps + 1)]
                for relay in relays:
                    self.forced.append((*relay, r.choice(('giant', 'O', 'supergiant', 'wolf_rayet')), 'route'))
                self.bridges += list(zip(relays, relays[1:]))
                band = np.abs((self.cy[:, None] - y) * dx - (self.cx[None, :] - x) * dy) <= 9
                self.owner[band & (self.owner == zid)] = self.add_zone('route', y, x)

    def place_seeds(self):
        g, r = nprng(self.key, 'seeds'), rng(self.key, 'seeds')
        jitter = value_noise(g, (self.gh, self.gw), [(6, 1.0)])
        free = self.owner == -1
        nearest = np.min([self.dist(self.zones[i]['y'], self.zones[i]['x']) for i in self.cradles], axis=0)

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

        far = self.d1 > CRADLE_RADIUS + 50
        inner = self.edge > 120
        n = len(self.cradles)
        # The prizes are where several cradles are at the same distance : nobody is favoured
        pick('amas_dense', max(1, round(self.W * self.H / 800_000)), -self.d1 - 60 * jitter, self.edge > 200, 150)
        pick('oasis', round(0.6 * n), (self.d3 - self.d1) + 40 * jitter, far & inner, 120)
        pick('carrefour', round(0.4 * n), (self.d2 - self.d1) + 60 * jitter, far & inner, 110)
        pick('veine', round(0.4 * n), (self.d2 - self.d1) + 80 * jitter - 40 * (self.rift_dist < 60), far & inner, 110)
        if r.random() < 0.7:
            pick('coeur_noir', 1, -self.d1 + 100 * jitter, (self.d1 > 160) & inner, 150)

        # The vestiges of the hunting mode : on the east side, behind a rift if possible, from a start on the west side
        candidates = np.flatnonzero(free & (self.cx[None, :] > 0.75 * self.W) & (self.edge > 60) & (nearest >= 100))
        best = None
        for flat in g.choice(candidates, size=min(200, len(candidates)), replace=False) if len(candidates) else ():
            i, j = divmod(int(flat), self.gw)
            line = np.linspace(0, 1, 300)
            ys, xs = self.H / 2 + line * (self.cy[i] - self.H / 2), line * self.cx[j]
            crossed = bool(self.rift[np.minimum(ys // CELL, self.gh - 1).astype(int), np.minimum(xs // CELL, self.gw - 1).astype(int)].any())
            if best is None or (crossed, self.cx[j]) > best[0]:
                best = ((crossed, self.cx[j]), i, j)
        if best:
            seed('vestiges', self.cy[best[1]], self.cx[best[2]])

        for a in range(n):
            for b in range(a + 1, n):
                (ya, xa), (yb, xb) = [(self.zones[self.cradles[k]]['y'], self.zones[self.cradles[k]]['x']) for k in (a, b)]
                i, j = self.cell((ya + yb) / 2, (xa + xb) / 2)
                if math.dist((ya, xa), (yb, xb)) < 1.25 * self.cradle_spacing and free[i, j] and nearest[i, j] >= 70:
                    seed('marche', self.cy[i], self.cx[j])

        names, weights = list(FREE_ZONES), list(FREE_ZONES.values())
        for flat in g.permutation(np.flatnonzero(free)):
            i, j = divmod(int(flat), self.gw)
            if nearest[i, j] >= 100:
                kind_name = r.choices(names, weights)[0]
                if kind_name in DANGEROUS and self.d1[i, j] < 170:
                    kind_name = 'plaine'
                if kind_name == 'plaine' and self.d1[i, j] < CRADLE_RADIUS + 40:
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
                    new.append(self.add_zone('marche' if self.d1[i, j] < CRADLE_RADIUS + 120 else 'plaine', self.cy[i], self.cx[j]))
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
            around = self.owner[dilate(mask) & ~mask]
            around = [z for z in around.tolist() if self.zones[z]['kind'] not in STAMPED]
            if around:
                self.owner[mask] = Counter(around).most_common(1)[0][0]

    ####################################################################################################################
    # SYSTEMS

    def place_systems(self):
        g = nprng(self.key, 'systems')
        kinds = self.zone_kinds()
        density = np.array([ZONES[k]['density'] for k in kinds])[self.owner]
        amplitude = np.array([ZONES[k]['noise'] for k in kinds])[self.owner]
        r = rng(self.key, 'centres')
        for zid, zone in enumerate(self.zones):
            inside = self.owner == zid
            d = self.dist(zone['y'], zone['x'])[inside]
            if zone['kind'] in ('amas_dense', 'amas_globulaire'):
                sigma = 0.45 * ZONES[zone['kind']]['cap']
                density[inside] *= 0.5 + 2.5 * np.exp(-d ** 2 / (2 * sigma ** 2))
            elif zone['kind'] == 'coeur_noir':
                density[inside] *= np.where(d < 15, 0.05, 0.3 + 2.0 * np.exp(-(d - 32) ** 2 / (2 * 9 ** 2)))
                self.forced.append((zone['y'], zone['x'], 'black_hole', 'coeur_noir'))
            elif zone['kind'] == 'carrefour':
                for star in ('supergiant', 'O', 'B'):
                    self.forced.append((zone['y'] + r.uniform(-12, 12), zone['x'] + r.uniform(-12, 12), star, 'carrefour'))
        halo = kinds[self.owner] == 'halo'
        density[halo] *= np.clip(self.edge[halo] / self.halo_width[halo], 0.1, 1) ** 1.5
        # Filaments and voids in the open zones, as the cosmic web : ridges of a smooth noise
        ridges = 1 - np.abs(2 * value_noise(g, (self.gh, self.gw), [(10, 0.6), (28, 1.0)]) - 1)
        web = np.isin(kinds[self.owner], list(WEB))
        density[web] *= 0.15 + 2.0 * ridges[web] ** 3
        density = box_blur(density)  # Soft borders between zones

        # Zones at the scale of the unit, through a smooth warp : their borders wave instead of following the cells.
        # The rifts keep their exact band : a warp must never bring two systems closer across a rift.
        rows, cols = np.arange(self.H)[:, None], np.arange(self.W)[None, :]
        wy = (2 * value_noise(g, (self.H, self.W), [(12, 1.0)]) - 1) * WARP
        wx = (2 * value_noise(g, (self.H, self.W), [(12, 1.0)]) - 1) * WARP
        iy = np.clip(((rows + wy) // CELL).astype(int), 0, self.gh - 1)
        ix = np.clip(((cols + wx) // CELL).astype(int), 0, self.gw - 1)
        self.owner_u = self.owner[iy, ix]
        exact = np.zeros((self.H, self.W), bool)
        for zid, points, widths in self.rifts:  # Drawn again at the scale of the unit : a smooth band
            for (y, x), w in zip(points, widths):
                r = w / 2 + 3
                y0, y1, x0, x1 = max(int(y - r), 0), min(int(y + r) + 2, self.H), max(int(x - r), 0), min(int(x + r) + 2, self.W)
                disc = (rows[y0:y1] - y) ** 2 + (cols[:, x0:x1] - x) ** 2 <= r * r
                exact[y0:y1, x0:x1] |= disc
                self.owner_u[y0:y1, x0:x1][disc] = zid
        units = density[iy, ix] * (1 + amplitude[iy, ix] * 0.6 * (2 * value_noise(g, (self.H, self.W), [(6, 0.6), (25, 1.0)]) - 1))
        units[np.isin(kinds[self.owner_u], ('faille', 'route')) | exact] = 0
        chance = np.minimum(units * DENSITY * self.W * self.H / units.sum(), 0.6)
        ys, xs = np.nonzero(g.random((self.H, self.W)) < chance)

        # Star class and system type, depending on the zone
        zone_of = self.owner_u[ys, xs]
        system_kinds = kinds[zone_of]
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
        for y, x, star, why in self.forced:
            y, x = min(max(int(round(y)), 0), self.H - 1), min(max(int(round(x)), 0), self.W - 1)
            i = at.get((y, x))
            if i is None:
                i = at[(y, x)] = self.add_system(y, x, star, why)
            self.cls[i], self.role[i] = CLASSES.index(star), why

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

    def place_homes(self):
        r = rng(self.key, 'homes')
        zone_of = self.system_zones()
        homes = []
        for zid in self.cradles:
            zone = self.zones[zid]
            candidates = [i for i in np.flatnonzero(zone_of == zid).tolist() if not self.role[i]
                          and math.hypot(self.ys[i] - zone['y'], self.xs[i] - zone['x']) <= 0.5 * CRADLE_RADIUS]
            r.shuffle(candidates)
            spacing = HOME_SPACING
            while True:
                chosen = []
                for i in candidates:
                    if all(math.hypot(self.ys[i] - self.ys[h], self.xs[i] - self.xs[h]) >= spacing for h in chosen):
                        chosen.append(i)
                        if len(chosen) == HOMES_PER_CRADLE:
                            break
                if len(chosen) == HOMES_PER_CRADLE or spacing < 8:
                    break
                spacing *= 0.9
            homes += chosen
        self.homes = np.array(homes, np.int64)
        self.stype[self.homes] = T['native']
        self.cls[self.homes] = [CLASSES.index(r.choice(('F', 'G', 'K'))) for _ in homes]
        self.role[self.homes] = 'monde_natal'

        vestiges = [i for i, zone in enumerate(self.zones) if zone['kind'] == 'vestiges']
        if vestiges:
            zone = self.zones[vestiges[0]]
            inside = np.flatnonzero(zone_of == vestiges[0])
            if len(inside):
                i = inside[np.argmin(np.hypot(self.ys[inside] - zone['y'], self.xs[inside] - zone['x']))]
                self.stype[i], self.role[i] = T['vestige'], 'vestige'
        self.apply_kit(r)

    def apply_kit(self, r):
        # A floor and a ceiling around each home : the same start for everyone, whatever the luck of the draw
        big_choices = [CLASSES.index(c) for c in ('A', 'B', 'giant', 'O')]
        for _ in range(6):  # The rings of neighbouring homes overlap : a few passes settle them
            for h in r.sample(self.homes.tolist(), len(self.homes)):
                d = np.hypot(self.ys - self.ys[h], self.xs - self.xs[h])
                movable = self.role == ''
                for what, near, far, least, most in KIT:
                    ring = (d >= near) & (d <= far)
                    has = ring & (BIG_IDX[self.cls] if what == 'big' else self.stype == T[what])
                    count = int(has.sum())
                    if count < least:
                        pool = ring & movable & (self.stype == T['standard'])
                        pool &= ~BIG_IDX[self.cls] if what == 'big' else np.ones_like(pool)
                        for i in r.sample(np.flatnonzero(pool).tolist(), min(least - count, int(pool.sum()))):
                            if what == 'big':
                                self.cls[i] = r.choice(big_choices)
                            else:
                                self.stype[i] = T[what]
                    elif count > most:
                        extra = np.flatnonzero(has & movable).tolist()
                        for i in r.sample(extra, min(count - most, len(extra))):
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
        pairs = np.unique(np.sort(np.stack([cells[a][keep], cells[b][keep]], 1), axis=1), axis=0) if keep.any() else []
        n = len(nodes)
        s, t = 2 * n, 2 * n + 1
        arcs = []
        for c, v in nodes.items():
            y, x = (c // width + 0.5) * size, (c % width + 0.5) * size
            source, sink = is_source(y, x, c), is_sink(y, x, c)
            arcs.append((2 * v, 2 * v + 1, INF if source or sink else 1))
            if source:
                arcs.append((s, 2 * v, INF))
            if sink:
                arcs.append((2 * v + 1, t, INF))
        for c1, c2 in (pairs.tolist() if len(pairs) else []):
            u, v = nodes[c1], nodes[c2]
            arcs += [(2 * u + 1, 2 * v, INF), (2 * v + 1, 2 * u, INF)]
        flow, reached = max_flow(2 * n + 2, arcs, s, t)
        cut = [((c // width) * size, (c % width) * size) for c, v in nodes.items() if reached[2 * v] and not reached[2 * v + 1]]
        return flow, cut, size

    def path_lengths(self, source):
        both = np.concatenate([self.edges, self.edges[:, ::-1]])
        both = both[np.argsort(both[:, 0], kind='stable')]
        starts = np.searchsorted(both[:, 0], np.arange(self.n + 1)).tolist()
        neighbours = both[:, 1].tolist()
        weights = np.hypot(self.ys[both[:, 0]] - self.ys[both[:, 1]], self.xs[both[:, 0]] - self.xs[both[:, 1]]).tolist()
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
        zone_of = self.system_zones()
        kinds = self.zone_kinds()
        west, east = 0.12 * self.W, 0.88 * self.W
        m['ouest_est'] = self.corridors(lambda y, x, c: x < west, lambda y, x, c: x > east)
        m['nord_sud'] = self.corridors(lambda y, x, c: y < 0.12 * self.H, lambda y, x, c: y > 0.88 * self.H)
        treasure = [i for i in np.flatnonzero(self.role == 'vestige').tolist()]
        m['vestiges'] = None
        if treasure:  # Every route that reaches the surroundings of the vestiges
            ty, tx = self.ys[treasure[0]], self.xs[treasure[0]]
            m['vestiges'] = self.corridors(lambda y, x, c: x < west, lambda y, x, c: math.hypot(y - ty, x - tx) <= 80)

        # Equity around each home
        rows = []
        for h in self.homes.tolist():
            d = np.hypot(self.ys - self.ys[h], self.xs - self.xs[h])
            others = d[self.homes]
            row = {'systèmes à 25 u': int((d <= 25).sum()) - 1}
            for what, near, far, least, most in KIT[:4]:  # The same rings as the kit
                has = BIG_IDX[self.cls] if what == 'big' else self.stype == T[what]
                row[f'{"grandes étoiles" if what == "big" else what} de {near} à {far} u'] = int(((d >= near) & (d <= far) & has).sum())
            row['monde natal le plus proche'] = round(float(np.min(others[others > 0])), 1) if len(self.homes) > 1 else 0
            counts = list(row.values())
            row['score'] = round(1.5 * counts[1] + 2 * counts[2] + counts[3] + 3 * counts[4] + counts[0] / 30, 1)
            rows.append(row)
        m['equity'] = rows

        # Detour between cradles : length of the vortex path / straight line
        firsts = [h for h in self.homes.tolist()][::HOMES_PER_CRADLE]
        ratios = []
        for k, source in enumerate(firsts[:6]):
            dist = self.path_lengths(source)
            for target in firsts[k + 1:]:
                straight = math.hypot(self.ys[source] - self.ys[target], self.xs[source] - self.xs[target])
                ratios.append(round(dist[target] / straight, 2))
        m['detours'] = ratios


########################################################################################################################
# PICTURES AND REPORT


def font(size, bold=False):
    try:
        return ImageFont.truetype('arialbd.ttf' if bold else 'arial.ttf', size)
    except OSError:
        return ImageFont.load_default()


def render(sector, folder):
    scale = 2.0 if max(sector.W, sector.H) <= 1200 else 2400 / max(sector.W, sector.H)
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

    panel = round(480 * scale / 2)
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
        draw.ellipse([x - 9, y - 9, x + 9, y + 9], outline=(255, 0, 255), width=2)
    for h in sector.homes.tolist():
        x, y = sector.xs[h] * scale + dot / 2, sector.ys[h] * scale + dot / 2
        draw.ellipse([x - 7, y - 7, x + 7, y + 7], outline=(90, 255, 150), width=2)
        draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=(255, 255, 255))
    for i in np.flatnonzero(sector.role == 'vestige').tolist():
        x, y = sector.xs[i] * scale, sector.ys[i] * scale
        draw.polygon([(x, y - 12), (x + 9, y), (x, y + 12), (x - 9, y)], fill=(255, 215, 0), outline=(0, 0, 0))

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
        size = int(np.clip(11 + math.sqrt(sizes[zid]) * CELL / 16, 13, 30) * scale / 2)
        light = tuple(int(c * 0.55 + 255 * 0.45) for c in spec['colour'])
        draw.text((sector.cx[j] * scale, sector.cy[i] * scale), spec['label'], fill=light, font=font(size, True),
                  anchor='mm', stroke_width=3, stroke_fill=(0, 0, 0))

    # Legend
    x0, y = width + 24 * scale / 2, 24 * scale / 2
    big_font, text_font, line = font(int(24 * scale / 2), True), font(int(15 * scale / 2)), 21 * scale / 2
    m = sector.measures
    draw.text((x0, y), f'Essai « {sector.key} »', fill=(255, 255, 255), font=big_font)
    y += 40 * scale / 2
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
            draw.rectangle([x0, y + 3, x0 + 26 * scale / 2, y + 17 * scale / 2], fill=tuple(int(c * 0.6) for c in spec['colour']),
                           outline=spec['colour'])
            draw.text((x0 + 36 * scale / 2, y), spec['label'], fill=(220, 220, 220), font=text_font)
            y += line
    y += line / 2
    draw.text((x0, y), 'Grandes étoiles (portée des vortex)', fill=(255, 255, 255), font=text_font)
    y += line
    for star in ('A', 'B', 'giant', 'O', 'wolf_rayet', 'supergiant', 'black_hole'):
        r = (0.8 + 0.8 * STARS[star][3]) * scale * 0.75
        cx, cy = x0 + 13 * scale / 2, y + 9 * scale / 2
        if star == 'black_hole':
            draw.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], fill=(0, 0, 0), outline=(255, 255, 255), width=2)
        else:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=STARS[star][2])
        draw.text((x0 + 36 * scale / 2, y), f'{STAR_NAMES[star]} : {STARS[star][1]} u', fill=(220, 220, 220), font=text_font)
        y += line
    draw.text((x0, y), 'Petites étoiles : 5 à 9 u', fill=(220, 220, 220), font=text_font)
    y += line * 1.5
    for marker, text in (('home', 'Monde natal'), ('bridge', 'Vortex prévu (tête de pont, route)'),
                         ('repair', 'Étoile ajoutée ou agrandie (réparation)'),
                         ('vestige', 'Vestiges (mode chasse au trésor)'), ('cut', 'Goulot (6 couloirs ou moins)'),
                         ('island', 'Système isolé, inaccessible')):
        cx, cy = x0 + 13 * scale / 2, y + 9 * scale / 2
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
        draw.text((x0 + 36 * scale / 2, y), text, fill=(220, 220, 220), font=text_font)
        y += line
    canvas.save(os.path.join(folder, f'{sector.key}_zones.png'))


def report(sector, folder):
    m, zone_of = sector.measures, sector.system_zones()
    kinds = sector.zone_kinds()
    sizes = np.bincount(sector.owner_u.ravel(), minlength=len(sector.zones))
    lines = [f'Génération « {sector.key} » : secteur de {sector.W} × {sector.H} unités ({sector.W // 100} × {sector.H // 100} cases actuelles)',
             'Durées : ' + ', '.join(f'{name} {seconds:.1f} s' for name, seconds in sector.timings.items()), '',
             f'Systèmes : {sector.n} (densité moyenne {sector.n / sector.W / sector.H:.3f} / u²)', '', 'Zones :']
    for kind_name, spec in ZONES.items():
        ids = [zid for zid, zone in enumerate(sector.zones) if zone['kind'] == kind_name and sizes[zid]]
        if ids:
            count = int(np.isin(zone_of, ids).sum())
            lines.append(f'  {spec["label"]:<24} {len(ids):>3} zone(s)  {count:>6} systèmes  {sizes[ids].sum() / sector.W / sector.H:6.1%} de la surface')
    shares = Counter(CLASSES[c] for c in sector.cls.tolist())
    big = sum(v for c, v in shares.items() if c in BIG)
    lines += ['', f'Étoiles : {big / sector.n:.1%} de grandes étoiles (' +
              ', '.join(f'{STAR_NAMES[c]} {shares[c] / sector.n:.2%}' for c in STAR_NAMES if shares[c]) + ')']

    rows = m['equity']
    scores = [row['score'] for row in rows]
    lines += ['', f'Équité, autour de chacun des {len(rows)} mondes natals ({len(sector.cradles)} berceaux × {HOMES_PER_CRADLE}) :']
    for name in rows[0] if rows else ():
        lines.append(f'  {name:<30} {stats([row[name] for row in rows])}')
    if scores:
        lines.append(f'  écart du score : le meilleur a {max(scores) / min(scores):.2f} fois le score du plus faible')

    sizes_comp = np.bincount(sector.comp)
    islands = int((sector.comp != sector.main).sum())
    lines += ['', 'Connectivité (lien vortex si la distance ≤ portée de la plus grande des deux étoiles) :',
              f'  liens : {len(sector.edges)} ; réseau principal : {sizes_comp[sector.main] / sector.n:.1%} des systèmes',
              f'  mondes natals dans le réseau principal : {int((sector.comp[sector.homes] == sector.main).sum())} / {len(sector.homes)}',
              f'  systèmes isolés, inaccessibles : {islands} en {len(set(sector.comp.tolist())) - 1} îlots',
              f'  réparations : {len(sector.repairs)} ' + ' '.join(f'(îlot de {s} systèmes à {g} u)' for s, g in sector.repairs),
              f'  couloirs indépendants (carrés de 20 u) ouest↔est : {m["ouest_est"][0]}, nord↔sud : {m["nord_sud"][0]}',
              f'  mode chasse au trésor, du bord ouest aux vestiges : {m["vestiges"][0] if m["vestiges"] else "pas de vestiges"} couloirs',
              f'  détour entre berceaux (chemin par vortex / ligne droite) : {stats(m["detours"])}']

    lines += ['', 'Identifiants lisibles (y.x-orbite) comparés aux identifiants actuels :']
    for h in sector.homes[:3].tolist():
        y, x = int(sector.ys[h]), int(sector.xs[h])
        lines.append(f'  {y:03}.{x:03}-3   au lieu de   1000{y // 100:03}{x // 100:03}{y % 100:03}{x % 100:03}03')
    text = '\n'.join(lines) + '\n'
    with open(os.path.join(folder, f'{sector.key}_rapport.txt'), 'w', encoding='utf-8') as f:
        f.write(text)
    return text


def generate(key, width, height):
    sector = Sector(key, width, height)
    start = time.perf_counter()
    sector.layout()
    sector.place_systems()
    sector.place_homes()
    sector.timings['génération'] = time.perf_counter() - start
    start = time.perf_counter()
    sector.repair()
    sector.measure()
    sector.timings['contrôles'] = time.perf_counter() - start
    return sector


def check():
    global SECRET
    a, b = generate('controle', 400, 400), generate('controle', 400, 400)
    assert np.array_equal(a.owner, b.owner) and np.array_equal(a.ys, b.ys) and np.array_equal(a.cls, b.cls), 'Not deterministic'
    SECRET += '-autre'
    c = generate('controle', 400, 400)
    assert not (np.array_equal(a.ys, c.ys) if len(a.ys) == len(c.ys) else False), 'Another secret must give another map'
    assert (a.comp[a.homes] == a.main).all(), 'A home is out of the main network'
    print('OK : same secret, same map ; another secret, another map ; every home is reachable')


def main():
    sys.stdout.reconfigure(encoding='utf-8')  # The Windows console would choke on the accents
    if '--check' in sys.argv:
        return check()
    runs = [(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))] if len(sys.argv) == 4 else \
        [(f'essai-{i}', 1000, 1000) for i in range(1, 6)] + [('grand-1', 1600, 1600)]
    os.makedirs(OUT, exist_ok=True)
    summary = ['essai        taille      systèmes  zones  natals  écart équité  réseau  îlots  répar.  O↔E  N↔S  trésor  détour méd.  durée']
    for key, width, height in runs:
        sector = generate(key, width, height)
        start = time.perf_counter()
        render(sector, OUT)
        sector.timings['images'] = time.perf_counter() - start
        print(report(sector, OUT))
        m, scores = sector.measures, [row['score'] for row in sector.measures['equity']]
        detours = sorted(m['detours'])
        summary.append(f'{key:<12} {width}×{height:<6} {sector.n:>8}  {int((np.bincount(sector.owner_u.ravel()) > 0).sum()):>5}  {len(sector.homes):>6}'
                       f'  {max(scores) / min(scores):>12.2f}  {np.mean(sector.comp == sector.main):>6.1%}  {int((sector.comp != sector.main).sum()):>5}'
                       f'  {len(sector.repairs):>6}  {m["ouest_est"][0]:>3}  {m["nord_sud"][0]:>3}  {m["vestiges"][0] if m["vestiges"] else "-":>6}'
                       f'  {detours[len(detours) // 2] if detours else "-":>11}  {sum(sector.timings.values()):>4.1f} s')
    if len(runs) > 1:
        with open(os.path.join(OUT, 'resume.txt'), 'w', encoding='utf-8') as f:
            f.write('\n'.join(summary) + '\n')
        print('\n'.join(summary))


if __name__ == '__main__':
    main()
