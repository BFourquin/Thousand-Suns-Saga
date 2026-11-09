// Map of a sector (page /geography_sector/). Made to stay fluid with tens of thousands of systems :
// one canvas repainted as a whole, typed arrays instead of an object per system, a grid to find the system under the pointer,
// and the deposits of a resource only loaded when a search asks for them. The details of a system are on the map of its quadrant.

(function () {
    'use strict';

    var root = document.getElementById('qmap');
    if (!root) { return; }

    var C = window.TSSMap;
    var clamp = C.clamp, el = C.el, icon = C.icon;
    var data = JSON.parse(document.getElementById('qmap-data').textContent);
    var L = data.labels;

    var TERRITORY_RADIUS = 4.5;  // In light years, as the positions
    var LABELS_ABOVE_ZOOM = 20;  // Every name is shown when a light year takes more pixels
    var LABELS_MAX_MATCHES = 25;
    var LABELS_LIMIT = 800;  // Text is the slowest thing to paint
    var SPRITE_ABOVE_RADIUS = 1.5;  // Under it, a star is a dot of a few pixels and a square is enough
    var HIT_RADIUS = 10;  // In pixels
    var GRID_SIDE = 128;

    function byId(id) { return document.getElementById(id); }

    var scene = byId('qmap-scene'), canvas = byId('qmap-canvas'), tooltip = byId('qmap-tooltip'), detail = byId('qmap-detail');
    var ctx = canvas.getContext('2d');
    var accent = getComputedStyle(root).getPropertyValue('--q-accent').trim() || '#5aa9ff';


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // DATA

    var S = data.systems, count = S.y.length, size = data.size, perAxis = Math.ceil(size / data.quadrant_size);
    var xs = Float32Array.from(S.x), ys = Float32Array.from(S.y);
    var starRanks = Uint8Array.from(S.star), typeRanks = Uint8Array.from(S.type);
    var starInfos = data.stars.map(function (star) { return C.STARS[star.key] || C.UNKNOWN_STAR; });
    var radii = new Float32Array(count);
    var cells = new Uint16Array(count);
    var networkRanks = new Int8Array(count).fill(-1);
    var networks = Object.keys(data.vortex.nodes).sort();
    var isHabitable = data.types.map(function (type) { return /habitable|native/.test(type.key); });

    // Linked lists of the systems of each cell of a grid
    var gridHeads = new Int32Array(GRID_SIDE * GRID_SIDE).fill(-1), gridNext = new Int32Array(count);
    function gridCoordinate(value) { return clamp(Math.floor(value / size * GRID_SIDE), 0, GRID_SIDE - 1); }

    for (var rank = 0; rank < count; rank++) {
        radii[rank] = starInfos[starRanks[rank]].size;
        cells[rank] = Math.min(Math.floor(ys[rank] / data.quadrant_size), perAxis - 1) * perAxis + Math.min(Math.floor(xs[rank] / data.quadrant_size), perAxis - 1);
        var gridCell = gridCoordinate(ys[rank]) * GRID_SIDE + gridCoordinate(xs[rank]);
        gridNext[rank] = gridHeads[gridCell];
        gridHeads[gridCell] = rank;
    }
    networks.forEach(function (network, index) {
        data.vortex.nodes[network].forEach(function (node) { networkRanks[node] = index; });
    });

    C.colorGroups(data.empires, data.ententes, C.MINE_COLOR);
    var empiresById = {}, ententesById = {};
    data.empires.forEach(function (empire) { empiresById[empire.id] = empire; });
    data.ententes.forEach(function (entente) { ententesById[entente.id] = entente; });

    var coloniesOf = data.colonies;
    var colonisedRanks = Object.keys(coloniesOf).map(Number);
    var ownersOf = {}, ententesOf = {}, colonyWords = {};
    colonisedRanks.forEach(function (colonised) {
        var owners = {}, ententes = {};
        coloniesOf[colonised].forEach(function (colony) {
            owners[colony.owner] = true;
            empiresById[colony.owner].ententes.forEach(function (entente) { ententes[entente] = true; });
        });
        ownersOf[colonised] = Object.keys(owners).map(Number);
        ententesOf[colonised] = Object.keys(ententes).map(Number);
        colonyWords[colonised] = C.normalize(coloniesOf[colonised].map(function (colony) { return colony.name; }).concat(
            ownersOf[colonised].map(function (owner) { return empiresById[owner].civilisation + ' ' + empiresById[owner].commandant; })).join(' '));
    });

    function pad(value) { return String(value).padStart(3, '0'); }
    function seedOf(system) { return data.id + pad(S.y[system]) + pad(S.x[system]); }
    function quadrantIdOf(cell) { return data.id + ':' + Math.floor(cell / perAxis) + (cell % perAxis); }
    function starName(system) { return data.stars[starRanks[system]].name; }


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // STATE

    var state = {
        mode: 'star', focus: {}, hiddenNetworks: {}, highlightedNetwork: null, allLabels: false, territories: true,
        text: '', stars: {}, colony: '', type: '', resource: '', min: 0, vortexOnly: false
    };
    var preset = null, selected = null, selectedCell = null, hovered = -1, hoveredCell = -1;

    var matched = new Uint8Array(count), filtering = false, matchCount = count;
    var cellMatches = new Float64Array(perAxis * perAxis), cellMax = 0;
    var cellSystems = new Uint32Array(perAxis * perAxis);
    cells.forEach(function (cell) { cellSystems[cell]++; });

    var resourceValues = null, resourceMax = 1, resourceRequest = 0, loadedResources = {};
    var palette = [], buckets = [];
    var names = null;  // Normalized the first time a text is searched


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // PAINTING

    var frame = 0, dpr = 1, sprites = {};

    var mapView = C.createView({
        scene: scene, minX: 0, minY: 0, size: size, apply: resize, dragStart: hideTooltip,
        click: function (event) {
            var world = mapView.toWorld(event.clientX, event.clientY);
            var found = systemAt(world.x, world.y);
            if (found >= 0) { select(found); return; }
            selectCell(world.x >= 0 && world.y >= 0 && world.x < size && world.y < size ? cellAt(world.x, world.y) : null);
        },
        escape: function () { select(null); }
    });
    var view = mapView.view;

    function cellAt(x, y) { return Math.floor(y / data.quadrant_size) * perAxis + Math.floor(x / data.quadrant_size); }

    function resize() {
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        var width = Math.round(mapView.width() * dpr), height = Math.round(mapView.height() * dpr);
        if (canvas.width !== width || canvas.height !== height) {
            canvas.width = width;
            canvas.height = height;
        }
        repaint();
    }

    function repaint() {
        if (!frame) { frame = requestAnimationFrame(paint); }
    }

    // A glow painted once and stamped afterwards : a gradient for each of thousands of stars would be too slow
    function sprite(color, stops, withCore) {
        var key = color + (withCore ? '*' : '');
        if (sprites[key]) { return sprites[key]; }
        var image = document.createElement('canvas');
        image.width = image.height = 64;
        var context = image.getContext('2d');
        context.fillStyle = color;
        context.fillRect(0, 0, 64, 64);
        context.globalCompositeOperation = 'destination-in';
        var gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32);
        stops.forEach(function (stop) { gradient.addColorStop(stop[0], 'rgba(0,0,0,' + stop[1] + ')'); });
        context.fillStyle = gradient;
        context.fillRect(0, 0, 64, 64);
        if (withCore) {
            context.globalCompositeOperation = 'source-over';
            context.fillStyle = 'rgba(255,255,255,0.9)';
            context.beginPath();
            context.arc(32, 32, 5, 0, Math.PI * 2);
            context.fill();
        }
        sprites[key] = image;
        return image;
    }
    function starSprite(color) { return sprite(color, [[0, 1], [0.28, 1], [0.48, 0.35], [1, 0]], true); }
    function landSprite(color) { return sprite(color, [[0, 0.55], [1, 0]], false); }

    function paint() {
        frame = 0;
        var width = mapView.width(), height = mapView.height();
        var zoom = 1 / mapView.unit();
        var ox = width / 2 - view.cx * zoom, oy = height / 2 - view.cy * zoom;
        var base = clamp(zoom * 0.35, 0.7, 6);

        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, width, height);
        ctx.globalAlpha = 1;
        ctx.setLineDash([]);

        paintCells(zoom, ox, oy);
        if (state.territories && state.mode !== 'star') { paintTerritories(zoom, ox, oy); }
        paintVortex(zoom, ox, oy, base);

        var margin = 20;
        function paintDots(wanted, alpha) {
            ctx.globalAlpha = alpha;
            for (var c = 0; c < buckets.length; c++) {
                var bucket = buckets[c], image = null;
                ctx.fillStyle = palette[c];
                for (var j = 0; j < bucket.length; j++) {
                    var i = bucket[j];
                    if (filtering && matched[i] !== wanted) { continue; }
                    var sx = xs[i] * zoom + ox, sy = ys[i] * zoom + oy;
                    if (sx < -margin || sy < -margin || sx > width + margin || sy > height + margin) { continue; }
                    var r = radii[i] * base;
                    if (wanted && resourceValues) { r *= 1 + 0.9 * resourceValues[i] / resourceMax; }  // The richer, the bigger
                    if (r < SPRITE_ABOVE_RADIUS) {
                        // On whole pixels : without antialiasing, a square costs far less to paint
                        var side = Math.max(1, Math.round(r * 2));
                        ctx.fillRect(Math.round(sx - side / 2), Math.round(sy - side / 2), side, side);
                    } else {
                        image = image || starSprite(palette[c]);
                        ctx.drawImage(image, sx - r * 2.1, sy - r * 2.1, r * 4.2, r * 4.2);
                    }
                }
            }
        }
        if (filtering) { paintDots(0, 0.13); }
        paintDots(1, 1);
        ctx.globalAlpha = 1;

        paintRings(zoom, ox, oy, base);
        paintLabels(zoom, ox, oy, base, width, height);
    }

    function paintCells(zoom, ox, oy) {
        var side = data.quadrant_size * zoom;

        // Where the search finds something, the way to read it on a map too wide to see each system
        if (filtering && cellMax > 0) {
            ctx.fillStyle = accent;
            for (var cell = 0; cell < cellMatches.length; cell++) {
                if (!cellMatches[cell]) { continue; }
                ctx.globalAlpha = 0.04 + 0.28 * cellMatches[cell] / cellMax;
                ctx.fillRect(cell % perAxis * side + ox, Math.floor(cell / perAxis) * side + oy, side, side);
            }
            ctx.globalAlpha = 1;
        }

        if (zoom >= 3) {
            ctx.strokeStyle = 'rgba(255,255,255,0.05)';
            ctx.lineWidth = 1;
            ctx.beginPath();
            for (var fine = 0; fine <= size; fine += 10) {
                ctx.moveTo(fine * zoom + ox, oy);
                ctx.lineTo(fine * zoom + ox, size * zoom + oy);
                ctx.moveTo(ox, fine * zoom + oy);
                ctx.lineTo(size * zoom + ox, fine * zoom + oy);
            }
            ctx.stroke();
        }

        ctx.strokeStyle = 'rgba(255,255,255,0.2)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (var line = 0; line <= perAxis; line++) {
            ctx.moveTo(line * side + ox, oy);
            ctx.lineTo(line * side + ox, perAxis * side + oy);
            ctx.moveTo(ox, line * side + oy);
            ctx.lineTo(perAxis * side + ox, line * side + oy);
        }
        ctx.stroke();

        ctx.fillStyle = 'rgba(255,255,255,0.4)';
        ctx.font = '10px sans-serif';
        for (var mark = 0; mark <= perAxis; mark++) {
            ctx.fillText(mark * data.quadrant_size, mark * side + ox + 3, oy + 11);
            if (mark) { ctx.fillText(mark * data.quadrant_size, ox + 3, mark * side + oy + 11); }
        }

        [[hoveredCell, 'rgba(255,255,255,0.5)'], [selectedCell, '#ffffff']].forEach(function (outlined) {
            if (outlined[0] === null || outlined[0] < 0) { return; }
            ctx.strokeStyle = outlined[1];
            ctx.strokeRect(outlined[0] % perAxis * side + ox, Math.floor(outlined[0] / perAxis) * side + oy, side, side);
        });
    }

    function paintTerritories(zoom, ox, oy) {
        var radius = Math.max(TERRITORY_RADIUS * zoom, 8);
        var focused = Object.keys(state.focus).length > 0;
        ctx.globalCompositeOperation = 'screen';
        colonisedRanks.forEach(function (system) {
            groupsOf(system).forEach(function (group) {
                ctx.globalAlpha = !focused || state.focus[group] ? 1 : 0.1;
                ctx.drawImage(landSprite(colorOfGroup(group)), xs[system] * zoom + ox - radius, ys[system] * zoom + oy - radius, radius * 2, radius * 2);
            });
        });
        ctx.globalCompositeOperation = 'source-over';
        ctx.globalAlpha = 1;
    }

    function paintVortex(zoom, ox, oy, base) {
        var receding = filtering && !state.vortexOnly;
        networks.forEach(function (network) {
            if (state.hiddenNetworks[network]) { return; }
            var highlighted = state.highlightedNetwork === network;
            ctx.strokeStyle = C.NETWORK_COLORS[network];
            ctx.globalAlpha = highlighted ? 1 : (state.highlightedNetwork ? 0.12 : (receding ? 0.16 : (zoom < 2.5 ? 0.3 : 0.55)));
            ctx.lineWidth = highlighted ? 2.4 : 1.1;

            var links = data.vortex.links[network] || [];
            ctx.beginPath();
            for (var j = 0; j < links.length; j += 2) {
                ctx.moveTo(xs[links[j]] * zoom + ox, ys[links[j]] * zoom + oy);
                ctx.lineTo(xs[links[j + 1]] * zoom + ox, ys[links[j + 1]] * zoom + oy);
            }
            ctx.stroke();

            // Toward the neighbouring sectors
            ctx.setLineDash([5, 4]);
            ctx.beginPath();
            data.vortex.exits.forEach(function (exit) {
                if (exit.network !== network) { return; }
                var x = xs[exit.from], y = ys[exit.from];
                ctx.moveTo(x * zoom + ox, y * zoom + oy);
                ctx.lineTo((exit.direction === 'west' ? 0 : (exit.direction === 'east' ? size : x)) * zoom + ox,
                           (exit.direction === 'north' ? 0 : (exit.direction === 'south' ? size : y)) * zoom + oy);
            });
            ctx.stroke();

            if (base >= 1.2 || highlighted) {
                ctx.setLineDash([2, 2]);
                ctx.lineWidth = highlighted ? 1.6 : 1;
                ctx.beginPath();
                data.vortex.nodes[network].forEach(function (node) {
                    var sx = xs[node] * zoom + ox, sy = ys[node] * zoom + oy, r = radii[node] * base + 3;
                    ctx.moveTo(sx + r, sy);
                    ctx.arc(sx, sy, r, 0, Math.PI * 2);
                });
                ctx.stroke();
            }
            ctx.setLineDash([]);
        });
        ctx.globalAlpha = 1;
    }

    function ringColors(system) {
        if (state.mode !== 'star') { return groupsOf(system).map(colorOfGroup); }
        var colors = [];
        if (coloniesOf[system].some(function (colony) { return colony.is_mine; })) { colors.push(C.MINE_COLOR); }
        if (coloniesOf[system].some(function (colony) { return !colony.is_mine; })) { colors.push(C.OTHER_COLOR); }
        return colors;
    }

    function paintRings(zoom, ox, oy, base) {
        ctx.lineWidth = 1.6;
        colonisedRanks.forEach(function (system) {
            if (filtering && !matched[system]) { return; }
            var sx = xs[system] * zoom + ox, sy = ys[system] * zoom + oy, r = Math.max(radii[system] * base + 2.5, 3.5);
            // A system shared between several groups gets one arc for each of them
            ringColors(system).forEach(function (color, index, colors) {
                ctx.strokeStyle = color;
                ctx.beginPath();
                ctx.arc(sx, sy, r, index / colors.length * Math.PI * 2, (index + 1) / colors.length * Math.PI * 2);
                ctx.stroke();
            });
        });
        [[hovered, 'rgba(255,255,255,0.75)'], [selected, '#ffffff']].forEach(function (marked) {
            if (marked[0] === null || marked[0] < 0) { return; }
            ctx.strokeStyle = marked[1];
            ctx.beginPath();
            ctx.arc(xs[marked[0]] * zoom + ox, ys[marked[0]] * zoom + oy, Math.max(radii[marked[0]] * base + 5, 7), 0, Math.PI * 2);
            ctx.stroke();
        });
    }

    function paintLabels(zoom, ox, oy, base, width, height) {
        ctx.font = '11px sans-serif';
        ctx.lineWidth = 3;
        ctx.strokeStyle = 'rgba(3, 6, 13, 0.85)';
        ctx.fillStyle = '#dfe7f2';

        function label(system) {
            var sx = xs[system] * zoom + ox, sy = ys[system] * zoom + oy;
            if (sx < -60 || sy < -10 || sx > width || sy > height + 10) { return false; }
            var x = sx + radii[system] * base + 6;
            ctx.strokeText(S.name[system], x, sy + 4);
            ctx.fillText(S.name[system], x, sy + 4);
            return true;
        }

        var all = state.allLabels || zoom >= LABELS_ABOVE_ZOOM;
        var fewMatches = filtering && matchCount <= LABELS_MAX_MATCHES;
        var painted = 0;
        if (all || fewMatches) {
            for (var i = 0; i < count && painted < LABELS_LIMIT; i++) {
                if ((!filtering || matched[i]) && label(i)) { painted++; }
            }
        }
        // Once the empires fill a map, far away, their names would hide it
        if (!all && (colonisedRanks.length <= LABELS_MAX_MATCHES || zoom >= LABELS_ABOVE_ZOOM / 3)) {
            colonisedRanks.forEach(function (system) {
                if (!filtering || matched[system]) { label(system); }
            });
        }
        if (selected !== null) { label(selected); }
    }


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // COLORS AND LEGEND

    function groupsOf(system) {
        if (state.mode === 'empire') { return ownersOf[system] || []; }
        if (state.mode === 'entente') { return ententesOf[system] || []; }
        return [data.stars[starRanks[system]].key];
    }

    function colorOfGroup(group) {
        if (state.mode === 'empire') { return empiresById[group].color; }
        if (state.mode === 'entente') { return ententesById[group].color; }
        return (C.STARS[group] || C.UNKNOWN_STAR).color;
    }

    // The systems grouped by color : changing the color of a canvas for each of them would be the slowest part of painting
    function applyColors() {
        var ranksOfColor = {};
        palette = [];
        buckets = [];
        for (var i = 0; i < count; i++) {
            var groups = groupsOf(i);
            var color = groups.length ? colorOfGroup(groups[0]) : C.NEUTRAL_COLOR;
            if (ranksOfColor[color] === undefined) {
                ranksOfColor[color] = palette.length;
                palette.push(color);
                buckets.push([]);
            }
            buckets[ranksOfColor[color]].push(i);
        }
    }

    function legendItems() {
        if (state.mode === 'empire') {
            return data.empires.map(function (empire) { return {key: empire.id, name: empire.civilisation, detail: empire.commandant, color: empire.color}; });
        }
        if (state.mode === 'entente') {
            return data.ententes.map(function (entente) { return {key: entente.id, name: entente.name, color: entente.color}; });
        }
        return starsBySize();
    }

    function starsBySize() {
        return data.stars.map(function (star, index) {
            return {key: star.key, name: star.name, color: starInfos[index].color, size: starInfos[index].size};
        }).sort(function (a, b) { return b.size - a.size; });
    }

    function renderLegend() {
        var list = byId('qmap-legend');
        list.textContent = '';
        var items = legendItems();
        if (!items.length) {
            el('li', 'qmap-empty', state.mode === 'empire' ? L.no_empire : L.no_entente, list);
            return;
        }
        var counts = {};
        for (var i = 0; i < count; i++) {
            if (state.mode === 'star' || ownersOf[i]) {
                groupsOf(i).forEach(function (group) { counts[group] = (counts[group] || 0) + 1; });
            }
        }
        items.forEach(function (item) {
            var button = el('button', 'qmap-legend-item', null, el('li', '', null, list));
            button.type = 'button';
            button.setAttribute('aria-pressed', !!state.focus[item.key]);
            el('span', 'qmap-dot', null, button).style.background = item.color;
            var itemNames = el('span', 'qmap-legend-name', item.name, button);
            if (item.detail) { el('small', '', item.detail, itemNames); }
            el('span', 'qmap-count', counts[item.key] || 0, button);
            button.addEventListener('click', function () {
                if (state.focus[item.key]) { delete state.focus[item.key]; } else { state.focus[item.key] = true; }
                button.setAttribute('aria-pressed', !!state.focus[item.key]);
                applyFilters();
            });
        });
    }

    function setMode(mode) {
        state.mode = mode;
        state.focus = {};
        root.querySelectorAll('[data-mode]').forEach(function (button) {
            button.setAttribute('aria-pressed', button.getAttribute('data-mode') === mode);
        });
        applyColors();
        renderLegend();
        applyFilters();
    }

    root.querySelectorAll('[data-mode]').forEach(function (button) {
        button.addEventListener('click', function () { setMode(button.getAttribute('data-mode')); });
    });

    root.querySelector('.qmap-controls').addEventListener('click', function (event) {
        var button = event.target.closest('button');
        var action = button && button.getAttribute('data-action');
        if (action === 'labels') {
            state.allLabels = !state.allLabels;
            button.setAttribute('aria-pressed', state.allLabels);
        }
        if (action === 'territories') {
            state.territories = !state.territories;
            button.setAttribute('aria-pressed', state.territories);
        }
        repaint();
    });


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // VORTEX NETWORKS

    (function renderNetworks() {
        var list = byId('qmap-networks');
        if (!networks.length) { el('li', 'qmap-empty', L.no_vortex, list); }
        networks.forEach(function (network) {
            var row = el('label', 'qmap-network', null, el('li', '', null, list));
            var input = el('input', '', null, row);
            input.type = 'checkbox';
            input.checked = true;
            el('span', 'qmap-dot', null, row).style.background = C.NETWORK_COLORS[network];
            el('span', 'qmap-legend-name', L.network + ' ' + L[network], row);
            el('span', 'qmap-count', data.vortex.nodes[network].length, row);
            input.addEventListener('change', function () {
                if (input.checked) { delete state.hiddenNetworks[network]; } else { state.hiddenNetworks[network] = true; }
                repaint();
            });
            row.addEventListener('pointerenter', function () { state.highlightedNetwork = network; repaint(); });
            row.addEventListener('pointerleave', function () { state.highlightedNetwork = null; repaint(); });
        });
    })();


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // SEARCH

    function matches(i) {
        if (state.text && names[i].indexOf(state.text) < 0 && (colonyWords[i] || '').indexOf(state.text) < 0 && seedOf(i).indexOf(state.text) !== 0) { return false; }
        if (state.anyStar && !state.stars[data.stars[starRanks[i]].key]) { return false; }
        if (state.colony) {
            var colonies = coloniesOf[i] || [];
            if (state.colony === 'any' && !colonies.length) { return false; }
            if (state.colony === 'free' && colonies.length) { return false; }
            if (state.colony === 'mine' && !colonies.some(function (colony) { return colony.is_mine; })) { return false; }
            if (state.colony === 'others' && !colonies.some(function (colony) { return !colony.is_mine; })) { return false; }
        }
        if (state.type === '__habitable' && !isHabitable[typeRanks[i]]) { return false; }
        if (state.type && state.type !== '__habitable' && data.types[typeRanks[i]].key !== state.type) { return false; }
        if (resourceValues && (resourceValues[i] === 0 || resourceValues[i] < state.min)) { return false; }
        if (state.vortexOnly && networkRanks[i] < 0) { return false; }
        if (state.anyFocus && !groupsOf(i).some(function (group) { return state.focus[group]; })) { return false; }
        return true;
    }

    function applyFilters() {
        state.anyStar = Object.keys(state.stars).length > 0;
        state.anyFocus = Object.keys(state.focus).length > 0;
        filtering = !!(state.text || state.anyStar || state.colony || state.type || resourceValues || state.vortexOnly || state.anyFocus);
        if (state.text && !names) { names = S.name.map(C.normalize); }

        var found = [];
        cellMatches.fill(0);
        for (var i = 0; i < count; i++) {
            matched[i] = !filtering || matches(i) ? 1 : 0;
            if (matched[i]) {
                found.push(i);
                cellMatches[cells[i]] += resourceValues ? resourceValues[i] : 1;
            }
        }
        cellMax = cellMatches.reduce(function (max, value) { return Math.max(max, value); }, 0);
        matchCount = found.length;
        byId('qmap-reset').hidden = !filtering && !state.resource;
        renderResults(found);
        repaint();
    }

    function renderResults(found) {
        byId('qmap-count').textContent = filtering
            ? (found.length ? found.length + ' ' + (found.length > 1 ? L.results : L.result) : L.no_result)
            : found.length + ' ' + L.all_systems;
        found.sort(resourceValues
            ? function (a, b) { return resourceValues[b] - resourceValues[a]; }
            : function (a, b) { return radii[b] - radii[a]; });

        var list = byId('qmap-results');
        list.textContent = '';
        found.slice(0, C.RESULTS_SHOWN).forEach(function (system) {
            var button = el('button', 'qmap-result', null, el('li', '', null, list));
            button.type = 'button';
            el('span', 'qmap-dot', null, button).style.background = starInfos[starRanks[system]].color;
            var itemNames = el('span', 'qmap-legend-name', S.name[system], button);
            el('small', '', starName(system) + ' · ' + S.y[system] + ' / ' + S.x[system], itemNames);
            if (coloniesOf[system]) { icon('fa-city', button); }
            if (networkRanks[system] >= 0) { icon('fa-circle-nodes', button).style.color = C.NETWORK_COLORS[networks[networkRanks[system]]]; }
            if (resourceValues) { el('span', 'qmap-count', resourceValues[system], button); }
            button.addEventListener('click', function () { select(system, true); });
            button.addEventListener('pointerenter', function () { hovered = system; repaint(); });
            button.addEventListener('pointerleave', function () { hovered = -1; repaint(); });
        });
        if (found.length > C.RESULTS_SHOWN) { el('li', 'qmap-empty', '+ ' + (found.length - C.RESULTS_SHOWN) + ' ' + L.more, list); }
    }

    byId('qmap-text').addEventListener('input', function () { clearPreset(); state.text = C.normalize(this.value.trim()); applyFilters(); });
    byId('qmap-colony').addEventListener('change', function () { clearPreset(); state.colony = this.value; applyFilters(); });
    byId('qmap-type').addEventListener('change', function () { clearPreset(); state.type = this.value; applyFilters(); });
    byId('qmap-vortex-only').addEventListener('change', function () { clearPreset(); state.vortexOnly = this.checked; applyFilters(); });
    byId('qmap-resource').addEventListener('change', function () { clearPreset(); setResource(this.value); });
    byId('qmap-min').addEventListener('input', function () {
        clearPreset();
        state.min = Number(this.value);
        byId('qmap-min-value').textContent = state.min;
        applyFilters();
    });

    function loadResource(resource) {
        if (loadedResources[resource]) { return Promise.resolve(loadedResources[resource]); }
        return fetch('/api_sector_deposits/?sector=' + data.id + '&resource=' + encodeURIComponent(resource)).then(function (response) {
            if (!response.ok) { throw new Error(response.status); }
            return response.json();
        }).then(function (deposits) {
            var values = new Uint16Array(count);
            deposits.indexes.forEach(function (system, index) { values[system] = deposits.values[index]; });
            loadedResources[resource] = values;
            return values;
        });
    }

    // topShare : only keep at first the richest part of the systems which hold this resource
    function setResource(resource, topShare) {
        var request = ++resourceRequest;
        state.resource = resource;
        state.min = 0;
        resourceValues = null;
        byId('qmap-resource').value = resource;
        byId('qmap-range').hidden = true;
        if (!resource) {
            applyFilters();
            return;
        }
        loadResource(resource).then(function (values) {
            if (request !== resourceRequest) { return; }  // Another one has been asked for in the meantime
            resourceValues = values;
            var held = Array.prototype.filter.call(values, Boolean).sort(function (a, b) { return a - b; });
            resourceMax = held.length ? held[held.length - 1] : 1;
            state.min = topShare && held.length ? held[Math.floor(held.length * (1 - topShare))] : 0;
            var range = byId('qmap-min');
            range.max = resourceMax;
            range.value = state.min;
            byId('qmap-min-value').textContent = state.min;
            byId('qmap-range').hidden = false;
            applyFilters();
        }).catch(function () {
            byId('qmap-count').textContent = L.load_error;
        });
    }

    (function fillSearchOptions() {
        starsBySize().forEach(function (star) {
            var chip = el('button', 'qmap-chip', null, byId('qmap-stars'));
            chip.type = 'button';
            chip.setAttribute('aria-pressed', false);
            chip.setAttribute('data-star', star.key);
            el('span', 'qmap-dot', null, chip).style.background = star.color;
            chip.appendChild(document.createTextNode(star.name));
            chip.addEventListener('click', function () {
                clearPreset();
                if (state.stars[star.key]) { delete state.stars[star.key]; } else { state.stars[star.key] = true; }
                syncStarChips();
                applyFilters();
            });
        });
        data.types.slice().sort(function (a, b) { return a.name.localeCompare(b.name); }).forEach(function (type) {
            el('option', '', type.name, byId('qmap-type')).value = type.key;
        });
        data.resources.slice().sort(function (a, b) { return a.name.localeCompare(b.name); }).forEach(function (resource) {
            el('option', '', resource.name, byId(resource.rare ? 'qmap-resources-rare' : 'qmap-resources-common')).value = resource.id;
        });
    })();

    function syncStarChips() {
        root.querySelectorAll('.qmap-chip').forEach(function (chip) {
            chip.setAttribute('aria-pressed', !!state.stars[chip.getAttribute('data-star')]);
        });
    }

    function clearSearch() {
        state.text = ''; state.stars = {}; state.colony = ''; state.type = ''; state.vortexOnly = false; state.focus = {};
        byId('qmap-text').value = '';
        byId('qmap-colony').value = '';
        byId('qmap-type').value = '';
        byId('qmap-vortex-only').checked = false;
        syncStarChips();
        renderLegend();
        setResource('');
    }

    function clearPreset() {
        preset = null;
        root.querySelectorAll('[data-preset]').forEach(function (button) { button.setAttribute('aria-pressed', false); });
    }

    var mostAbundant = data.resources.filter(function (resource) { return !resource.rare; })[0];

    var PRESETS = {
        largest: function () {
            data.stars.forEach(function (star, index) {
                if (starInfos[index].size >= C.LARGEST_STAR_SIZE) { state.stars[star.key] = true; }
            });
            syncStarChips();
        },
        colonized: function () { state.colony = 'any'; byId('qmap-colony').value = 'any'; },
        habitable: function () { state.type = '__habitable'; byId('qmap-type').value = '__habitable'; },
        rare: function () { setResource('__rare'); },
        concentration: function () { if (mostAbundant) { setResource(mostAbundant.id, 0.1); } },
        vortex: function () { state.vortexOnly = true; byId('qmap-vortex-only').checked = true; }
    };

    byId('qmap-presets').addEventListener('click', function (event) {
        var button = event.target.closest('[data-preset]');
        if (!button) { return; }
        var name = button.getAttribute('data-preset');
        var wasActive = preset === name;
        clearSearch();
        clearPreset();
        if (!wasActive) {
            preset = name;
            button.setAttribute('aria-pressed', true);
            PRESETS[name]();
        }
        applyFilters();
    });

    byId('qmap-reset').addEventListener('click', function () { clearPreset(); clearSearch(); });


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // UNDER THE POINTER

    // The closest system, among the ones the search keeps
    function systemAt(x, y) {
        var radius = HIT_RADIUS * mapView.unit();
        var best = -1, bestDistance = radius * radius;
        var rows = [gridCoordinate(y - radius), gridCoordinate(y + radius)], columns = [gridCoordinate(x - radius), gridCoordinate(x + radius)];
        for (var row = rows[0]; row <= rows[1]; row++) {
            for (var column = columns[0]; column <= columns[1]; column++) {
                for (var i = gridHeads[row * GRID_SIDE + column]; i >= 0; i = gridNext[i]) {
                    var dx = xs[i] - x, dy = ys[i] - y, distance = dx * dx + dy * dy;
                    if (distance < bestDistance && matched[i]) {
                        best = i;
                        bestDistance = distance;
                    }
                }
            }
        }
        return best;
    }

    function hideTooltip() { tooltip.hidden = true; }

    function setHovered(system, cell) {
        var network = system >= 0 && networkRanks[system] >= 0 ? networks[networkRanks[system]] : null;
        if (system !== hovered || cell !== hoveredCell || network !== state.highlightedNetwork) {
            hovered = system;
            hoveredCell = cell;
            state.highlightedNetwork = network;
            repaint();
        }
    }

    canvas.addEventListener('pointermove', function (event) {
        if (mapView.isDragging()) { return; }
        var world = mapView.toWorld(event.clientX, event.clientY);
        var system = systemAt(world.x, world.y);
        var inside = world.x >= 0 && world.y >= 0 && world.x < size && world.y < size;
        var cell = inside ? cellAt(world.x, world.y) : -1;
        setHovered(system, cell);

        if (system < 0 && !inside) {
            hideTooltip();
            return;
        }
        tooltip.textContent = '';
        if (system >= 0) {
            el('b', '', S.name[system], tooltip);
            el('div', '', starName(system) + ' · ' + S.y[system] + ' / ' + S.x[system], tooltip);
            if (ownersOf[system]) {
                el('div', '', ownersOf[system].map(function (owner) { return empiresById[owner].civilisation; }).join(', '), tooltip);
            }
            if (networkRanks[system] >= 0) {
                var network = networks[networkRanks[system]];
                el('div', '', L.network + ' ' + L[network], tooltip).style.color = C.NETWORK_COLORS[network];
            }
            if (resourceValues) { el('div', '', resourceName() + ' : ' + resourceValues[system], tooltip); }
        } else {
            el('b', '', L.quadrant + ' ' + quadrantLabel(cell), tooltip);
            el('div', '', cellSummary(cell), tooltip);
        }
        tooltip.hidden = false;
        var rect = scene.getBoundingClientRect();
        tooltip.style.left = Math.min(event.clientX - rect.left + 14, rect.width - tooltip.offsetWidth - 8) + 'px';
        tooltip.style.top = Math.min(event.clientY - rect.top + 14, rect.height - tooltip.offsetHeight - 8) + 'px';
    });

    canvas.addEventListener('pointerleave', function () {
        hideTooltip();
        setHovered(-1, -1);
    });

    function quadrantLabel(cell) { return Math.floor(cell / perAxis) + '-' + (cell % perAxis); }

    function resourceName() {
        return state.resource === '__rare' ? L.rare_resources : byId('qmap-resource').selectedOptions[0].textContent;
    }

    function cellSummary(cell) {
        var text = cellSystems[cell] + ' ' + L.all_systems;
        if (filtering && !resourceValues) { text = cellMatches[cell] + ' / ' + text; }
        if (resourceValues) { text += ' · ' + resourceName() + ' : ' + cellMatches[cell]; }
        return text;
    }


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // SELECTED SYSTEM OR QUADRANT

    function openDetail(title, subtitle) {
        detail.textContent = '';
        detail.hidden = false;
        var close = el('button', 'qmap-detail-close', null, detail);
        close.type = 'button';
        close.setAttribute('aria-label', '×');
        icon('fa-xmark', close);
        close.addEventListener('click', function () { select(null); });
        el('h3', 'qmap-detail-name', title, detail);
        el('p', 'qmap-detail-kind', subtitle, detail);
    }

    function linkButton(href, iconName, text) {
        var link = el('a', 'btn btn-default btn-sm btn-block', null, detail);
        link.href = href;
        icon(iconName, link);
        link.appendChild(document.createTextNode(' ' + text));
    }

    function renderSystem(system) {
        openDetail(S.name[system], starName(system) + ' · ' + data.types[typeRanks[system]].name);
        var facts = el('dl', 'qmap-facts', null, detail);
        el('dt', '', L.position, facts);
        el('dd', '', S.y[system] + ' / ' + S.x[system], facts);
        linkButton('/geography_quadrant/?system_id=' + seedOf(system), 'fa-map', L.open_quadrant_map);
        linkButton('/geography_system/?system_id=' + seedOf(system), 'fa-sun', L.open_system);

        el('h4', 'qmap-section', L.colonies, detail);
        if (!coloniesOf[system]) { el('p', 'qmap-empty', L.no_colony, detail); }
        (coloniesOf[system] || []).forEach(function (colony) {
            var row = el('div', 'qmap-colony', null, detail);
            el('span', 'qmap-dot', null, row).style.background = empiresById[colony.owner].color;
            var itemNames = el('span', 'qmap-legend-name', null, row);
            if (colony.id) {
                el('a', '', colony.name, itemNames).href = '/colony/?colony_id=' + colony.id;
            } else {
                itemNames.appendChild(document.createTextNode(colony.name));
            }
            el('small', '', empiresById[colony.owner].civilisation + ' · ' + empiresById[colony.owner].commandant, itemNames);
            empiresById[colony.owner].ententes.forEach(function (entente) {
                el('a', 'qmap-entente', ententesById[entente].name, itemNames).href = '/entente/?entente_id=' + entente;
            });
        });

        if (networkRanks[system] >= 0) {
            var network = networks[networkRanks[system]];
            el('h4', 'qmap-section', L.vortex, detail);
            el('p', '', L.network + ' ' + L[network], detail).style.color = C.NETWORK_COLORS[network];
        }
        if (resourceValues) {
            el('h4', 'qmap-section', L.deposits, detail);
            var deposit = el('div', 'qmap-deposit', null, detail);
            el('span', '', resourceName(), deposit);
            el('b', '', resourceValues[system], deposit);
        }
    }

    function select(system, reveal) {
        selected = system;
        selectedCell = null;
        detail.hidden = system === null;
        if (system !== null) {
            renderSystem(system);
            if (reveal) { mapView.reveal(xs[system], ys[system]); }
        }
        repaint();
    }

    function selectCell(cell) {
        if (cell === null) {
            select(null);
            return;
        }
        selected = null;
        selectedCell = cell;
        openDetail(L.quadrant + ' ' + quadrantLabel(cell), cellSummary(cell));
        linkButton('/geography_quadrant/?quadrant=' + quadrantIdOf(cell), 'fa-map', L.open_quadrant_map);
        repaint();
    }


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

    setMode('star');
    resize();

})();
