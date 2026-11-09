// The maps of the sector (/geography_sector/ : the whole map of the server) and of a quadrant (/geography_quadrant/ : one
// natural zone of it, the systems around it dimmed). Made to stay fluid with a hundred thousand systems : one canvas repainted
// as a whole, typed arrays instead of an object per system, a grid to find the system under the pointer, the zones drawn once
// on a small image, and from afar the systems too. The map of the sector comes apart from its page, compressed and cached.

(function () {
    'use strict';

    var root = document.getElementById('qmap');
    if (!root) { return; }

    var C = window.TSSMap;
    var clamp = C.clamp, el = C.el, icon = C.icon;
    var data = JSON.parse(document.getElementById('qmap-data').textContent);
    var L = data.labels;
    var isSector = data.mode === 'sector';

    function byId(id) { return document.getElementById(id); }

    if (isSector) {
        byId('qmap-count').textContent = L.loading;
        fetch('/api_sector_map/?v=' + data.version).then(function (response) {
            if (!response.ok) { throw new Error(response.status); }
            return response.json();
        }).then(start).catch(function () { byId('qmap-count').textContent = L.load_error; });
    } else {
        start({systems: data.systems, zones: data.zones, cell: data.cell,
               y: data.bounds.y, x: data.bounds.x, height: data.bounds.height, width: data.bounds.width});
    }

    function start(map) {

        var TERRITORY_RADIUS = 4.5;  // In light years, as the positions
        var LABELS_ABOVE_ZOOM = 20;  // Every name is shown when a light year takes more pixels
        var LABELS_MAX_MATCHES = 25;
        var LABELS_LIMIT = 800;  // Text is the slowest thing to paint
        var SPRITE_ABOVE_RADIUS = 1.5;  // Under it, a star is a dot of a few pixels and a square is enough
        var HIT_RADIUS = 10;  // In pixels
        var GRID_SIDE = 256;
        var STAMP_BELOW_ZOOM = 1.6;  // Farther, the systems of the sector are stamped once on an image : too many to paint each one
        var STAMP_MAX_SIDE = 2048;
        var AROUND_ALPHA = 0.3;  // The systems around a quadrant, which belong to the maps of their own zones
        var ZONE_LABEL_RADIUS = 22;  // In pixels : a smaller zone gets no name on the map of the sector

        var scene = byId('qmap-scene'), canvas = byId('qmap-canvas'), tooltip = byId('qmap-tooltip'), detail = byId('qmap-detail');
        var ctx = canvas.getContext('2d');
        var accent = getComputedStyle(root).getPropertyValue('--q-accent').trim() || '#5aa9ff';
        var probe = document.createElement('canvas').getContext('2d');

        function rgbOf(color) {
            probe.fillStyle = '#000';
            probe.fillStyle = color;
            var normalized = probe.fillStyle;  // #rrggbb, or rgba() for a transparent color
            if (normalized[0] === '#') {
                return [parseInt(normalized.slice(1, 3), 16), parseInt(normalized.slice(3, 5), 16), parseInt(normalized.slice(5, 7), 16)];
            }
            return normalized.match(/\d+/g).slice(0, 3).map(Number);
        }


        ////////////////////////////////////////////////////////////////////////////////////////////////////////////////
        // DATA

        var S = map.systems, count = S.y.length;
        var size = Math.max(map.width, map.height);
        var minX = (map.x || 0) - (size - map.width) / 2, minY = (map.y || 0) - (size - map.height) / 2;
        var xs = Float32Array.from(S.x), ys = Float32Array.from(S.y);
        var starRanks = Uint8Array.from(S.star), typeRanks = Uint8Array.from(S.type);
        var starInfos = S.stars.map(function (star) { return C.STARS[star.key] || C.UNKNOWN_STAR; });
        var isHabitable = S.types.map(function (type) { return /habitable|native/.test(type.key); });
        var radii = new Float32Array(count);
        var zones = map.zones, zoneIndex = {};
        zones.forEach(function (zone, index) { zoneIndex[zone.id] = index; zone.cells = 0; });
        var zoneRanks = new Int16Array(count);  // -1 : a zone this map doesn't hold
        var inZone = new Uint8Array(count);  // On the map of a quadrant, its own systems : the others are only around it
        var ownZone = isSector ? -1 : zoneIndex[data.id];
        var nativeZone = isSector && data.native_zone !== null && zoneIndex[data.native_zone] !== undefined ? zoneIndex[data.native_zone] : -1;

        // Linked lists of the systems of each cell of a grid
        var gridHeads = new Int32Array(GRID_SIDE * GRID_SIDE).fill(-1), gridNext = new Int32Array(count);
        function gridCoordinate(value, min) { return clamp(Math.floor((value - min) / size * GRID_SIDE), 0, GRID_SIDE - 1); }

        var ownCount = 0;
        for (var rank = 0; rank < count; rank++) {
            radii[rank] = starInfos[starRanks[rank]].size;
            zoneRanks[rank] = zoneIndex[S.zone[rank]] === undefined ? -1 : zoneIndex[S.zone[rank]];
            inZone[rank] = isSector || S.zone[rank] === data.id ? 1 : 0;
            ownCount += inZone[rank];
            var gridCell = gridCoordinate(ys[rank], minY) * GRID_SIDE + gridCoordinate(xs[rank], minX);
            gridNext[rank] = gridHeads[gridCell];
            gridHeads[gridCell] = rank;
        }

        // The vortex of a quadrant : pairs of ranks
        var links = data.vortex || [];
        var degree = new Uint16Array(count);
        for (var link = 0; link < links.length; link++) { degree[links[link]]++; }

        C.colorGroups(data.empires, data.ententes, C.MINE_COLOR);
        var empiresById = {}, ententesById = {}, resourcesById = {};
        data.empires.forEach(function (empire) { empiresById[empire.id] = empire; });
        data.ententes.forEach(function (entente) { ententesById[entente.id] = entente; });
        data.resources.forEach(function (resource) { resourcesById[resource.id] = resource; });

        // The colonies of the sector come by the seed of their system, those of a quadrant by its rank
        var coloniesOf = data.colonies;
        if (isSector) {
            var rankAt = new Map();
            for (var i0 = 0; i0 < count; i0++) { rankAt.set(S.y[i0] * 100000 + S.x[i0], i0); }
            coloniesOf = {};
            Object.keys(data.colonies).forEach(function (seed) {
                var at = rankAt.get((+seed.slice(4, 7) * 100 + +seed.slice(10, 13)) * 100000 + +seed.slice(7, 10) * 100 + +seed.slice(13, 16));
                if (at !== undefined) { coloniesOf[at] = data.colonies[seed]; }
            });
        }
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

        function pad(value, length) { return String(value).padStart(length || 3, '0'); }
        function seedOf(system) {
            var y = S.y[system], x = S.x[system];
            return data.server_seed + pad(Math.floor(y / 100)) + pad(Math.floor(x / 100)) + pad(y % 100) + pad(x % 100);
        }
        function column(x) {  // 0 -> A, 25 -> Z, 26 -> AA : as data.locations
            var letters = '';
            for (x += 1; x; x = Math.floor((x - 1) / 26)) { letters = String.fromCharCode(65 + (x - 1) % 26) + letters; }
            return letters;
        }
        function placeOf(system) {  // C6-12.55 : the readable place of data.locations
            var y = S.y[system], x = S.x[system];
            return column(Math.floor(x / 100)) + (Math.floor(y / 100) + 1) + '-' + pad(x % 100, 2) + '.' + pad(y % 100, 2);
        }
        function starName(system) { return S.stars[starRanks[system]].name; }
        function zoneUrl(index) { return '/geography_quadrant/?zone=' + zones[index].id; }


        ////////////////////////////////////////////////////////////////////////////////////////////////////////////////
        // STATE

        var state = {mode: 'star', focus: {}, allLabels: false, territories: true, vortex: true, text: '', stars: {}, colony: '', type: '', resource: '', min: 0};
        var preset = null, selected = null, selectedZone = -1, hovered = -1, hoveredZone = -1;

        var matched = new Uint8Array(count), filtering = false, matchCount = ownCount;
        var zoneMatches = new Float64Array(zones.length), zoneMax = 0;
        var zoneSystems = new Uint32Array(zones.length);
        for (var i1 = 0; i1 < count; i1++) { if (zoneRanks[i1] >= 0) { zoneSystems[zoneRanks[i1]]++; } }

        var resourceValues = null, resourceMax = 1, resourceRequest = 0, loadedResources = {};
        var palette = [], buckets = [], colorRanks = new Uint16Array(count);
        var names = null;  // Normalized the first time a text is searched, as the readable places
        var places = null;


        ////////////////////////////////////////////////////////////////////////////////////////////////////////////////
        // THE ZONES : an image with a pixel for each cell of the generator, drawn again when what it shows changes

        var cell = map.cell;
        var row0 = Math.floor(minY / cell), col0 = Math.floor(minX / cell), side = Math.ceil(size / cell) + 2;
        var owner = new Int16Array(side * side).fill(-1);
        zones.forEach(function (zone, index) {
            zone.shape.forEach(function (run) {
                var row = run[0] - row0;
                if (row < 0 || row >= side) { return; }
                for (var col = Math.max(run[1] - col0, 0); col < Math.min(run[1] + run[2] - col0, side); col++) {
                    owner[row * side + col] = index;
                    zone.cells++;
                }
            });
        });
        var zoneColors = zones.map(function (zone) { return rgbOf(zone.color); });
        var accentRgb = rgbOf(accent), white = [255, 255, 255];
        var zonesImage = document.createElement('canvas');
        zonesImage.width = zonesImage.height = side;
        var zonesContext = zonesImage.getContext('2d');
        var zonesPixels = zonesContext.createImageData(side, side);

        function zoneAt(x, y) {
            var row = Math.floor(y / cell) - row0, col = Math.floor(x / cell) - col0;
            return row < 0 || col < 0 || row >= side || col >= side ? -1 : owner[row * side + col];
        }

        function renderZones() {
            var pixels = zonesPixels.data;
            var heat = isSector && filtering && zoneMax > 0;
            for (var k = 0; k < owner.length; k++) {
                var z = owner[k], p = k * 4;
                if (z < 0) { pixels[p + 3] = 0; continue; }
                var col = k % side;
                var border = col === 0 || col === side - 1 || k < side || k >= owner.length - side ||
                             owner[k - 1] !== z || owner[k + 1] !== z || owner[k - side] !== z || owner[k + side] !== z;
                var rgb = zoneColors[z], alpha;
                if (heat) {  // Where the search finds something : a map too wide to see each system
                    rgb = accentRgb;
                    alpha = zoneMatches[z] ? 0.08 + 0.42 * zoneMatches[z] / zoneMax : 0.015;
                    if (border) { alpha = Math.max(alpha, 0.22); rgb = zoneColors[z]; }
                } else {
                    alpha = border ? 0.42 : (isSector || z === ownZone ? 0.09 : 0.035);
                }
                if (z === hoveredZone || z === selectedZone) {
                    alpha += border ? 0.45 : 0.08;
                    if (border) { rgb = white; }
                }
                if (border && z === nativeZone) { rgb = accentRgb; alpha = 0.95; }
                pixels[p] = rgb[0]; pixels[p + 1] = rgb[1]; pixels[p + 2] = rgb[2]; pixels[p + 3] = Math.min(alpha, 1) * 255;
            }
            zonesContext.putImageData(zonesPixels, 0, 0);
        }


        ////////////////////////////////////////////////////////////////////////////////////////////////////////////////
        // THE SYSTEMS OF THE SECTOR FROM AFAR : stamped on an image instead of being painted one by one

        var stampScale = Math.min(1, STAMP_MAX_SIDE / size), stampSide = Math.ceil(size * stampScale) + 2;
        var stampImage = null, stampContext = null, stampPixels = null;

        function renderStamps() {
            if (!isSector) { return; }
            if (!stampImage) {
                stampImage = document.createElement('canvas');
                stampImage.width = stampImage.height = stampSide;
                stampContext = stampImage.getContext('2d');
                stampPixels = stampContext.createImageData(stampSide, stampSide);
            }
            var pixels = stampPixels.data, colors = palette.map(rgbOf);
            pixels.fill(0);
            for (var i = 0; i < count; i++) {
                var rgb = colors[colorRanks[i]], alpha = !filtering || matched[i] ? 255 : 30;
                var px = Math.floor((xs[i] - minX) * stampScale), py = Math.floor((ys[i] - minY) * stampScale);
                for (var dy = 0; dy < 2; dy++) {
                    for (var dx = 0; dx < 2; dx++) {
                        var p = ((py + dy) * stampSide + px + dx) * 4;
                        if (pixels[p + 3] >= alpha) { continue; }  // A system kept by the search stays above the others
                        pixels[p] = rgb[0]; pixels[p + 1] = rgb[1]; pixels[p + 2] = rgb[2]; pixels[p + 3] = alpha;
                    }
                }
            }
            stampContext.putImageData(stampPixels, 0, 0);
        }


        ////////////////////////////////////////////////////////////////////////////////////////////////////////////////
        // PAINTING

        var frame = 0, dpr = 1, sprites = {};

        var mapView = C.createView({
            scene: scene, minX: minX, minY: minY, size: size, apply: resize, dragStart: hideTooltip,
            click: function (event) {
                var world = mapView.toWorld(event.clientX, event.clientY);
                var found = systemAt(world.x, world.y);
                if (found >= 0) { select(found); return; }
                selectZone(zoneAt(world.x, world.y));
            },
            escape: function () { select(null); }
        });
        var view = mapView.view;

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

            ctx.imageSmoothingEnabled = cell * zoom < 4;  // Close, the cells of the zones keep their edges
            ctx.drawImage(zonesImage, (col0 * cell) * zoom + ox, (row0 * cell) * zoom + oy, side * cell * zoom, side * cell * zoom);
            ctx.imageSmoothingEnabled = true;

            if (state.territories && state.mode !== 'star') { paintTerritories(zoom, ox, oy); }
            if (state.vortex && links.length) { paintVortex(zoom, ox, oy); }

            if (isSector && zoom < STAMP_BELOW_ZOOM) {
                ctx.drawImage(stampImage, minX * zoom + ox, minY * zoom + oy, stampSide / stampScale * zoom, stampSide / stampScale * zoom);
            } else {
                paintDots(zoom, ox, oy, base, width, height);
            }

            paintRings(zoom, ox, oy, base);
            if (isSector) { paintZoneNames(zoom, ox, oy); }
            paintLabels(zoom, ox, oy, base, width, height);
            placeExits(zoom, ox, oy, width, height);
        }

        function paintDots(zoom, ox, oy, base, width, height) {
            var margin = 20;
            // pass 0 : around the quadrant, 1 : left aside by the search, 2 : shown
            function passOf(i) { return !inZone[i] ? 0 : (filtering && !matched[i] ? 1 : 2); }
            [[0, AROUND_ALPHA], [1, 0.13], [2, 1]].forEach(function (pass) {
                ctx.globalAlpha = pass[1];
                for (var c = 0; c < buckets.length; c++) {
                    var bucket = buckets[c], image = null;
                    ctx.fillStyle = palette[c];
                    for (var j = 0; j < bucket.length; j++) {
                        var i = bucket[j];
                        var sx = xs[i] * zoom + ox, sy = ys[i] * zoom + oy;
                        if (sx < -margin || sy < -margin || sx > width + margin || sy > height + margin || passOf(i) !== pass[0]) { continue; }
                        var r = radii[i] * base;
                        if (pass[0] === 2 && resourceValues) { r *= 1 + 0.9 * resourceValues[i] / resourceMax; }  // The richer, the bigger
                        if (r < SPRITE_ABOVE_RADIUS) {
                            // On whole pixels : without antialiasing, a square costs far less to paint
                            var square = Math.max(1, Math.round(r * 2));
                            ctx.fillRect(Math.round(sx - square / 2), Math.round(sy - square / 2), square, square);
                        } else {
                            image = image || starSprite(palette[c]);
                            ctx.drawImage(image, sx - r * 2.1, sy - r * 2.1, r * 4.2, r * 4.2);
                        }
                    }
                }
            });
            ctx.globalAlpha = 1;
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

        function paintVortex(zoom, ox, oy) {
            var marked = selected !== null ? selected : hovered;
            ctx.strokeStyle = C.NETWORK_COLORS.alpha;
            ctx.lineWidth = 1;
            ctx.globalAlpha = marked >= 0 ? 0.06 : (filtering ? 0.06 : (zoom < 2.5 ? 0.09 : 0.2));  // Thousands of links : a mist from afar
            ctx.beginPath();
            for (var j = 0; j < links.length; j += 2) {
                ctx.moveTo(xs[links[j]] * zoom + ox, ys[links[j]] * zoom + oy);
                ctx.lineTo(xs[links[j + 1]] * zoom + ox, ys[links[j + 1]] * zoom + oy);
            }
            ctx.stroke();
            if (marked >= 0 && degree[marked]) {  // The ways out of the system under the pointer or selected
                ctx.globalAlpha = 1;
                ctx.lineWidth = 2;
                ctx.beginPath();
                for (var k = 0; k < links.length; k += 2) {
                    if (links[k] === marked || links[k + 1] === marked) {
                        ctx.moveTo(xs[links[k]] * zoom + ox, ys[links[k]] * zoom + oy);
                        ctx.lineTo(xs[links[k + 1]] * zoom + ox, ys[links[k + 1]] * zoom + oy);
                    }
                }
                ctx.stroke();
            }
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
                ctx.globalAlpha = inZone[system] ? 1 : AROUND_ALPHA * 2;
                // A system shared between several groups gets one arc for each of them
                ringColors(system).forEach(function (color, index, colors) {
                    ctx.strokeStyle = color;
                    ctx.beginPath();
                    ctx.arc(sx, sy, r, index / colors.length * Math.PI * 2, (index + 1) / colors.length * Math.PI * 2);
                    ctx.stroke();
                });
            });
            ctx.globalAlpha = 1;
            [[hovered, 'rgba(255,255,255,0.75)'], [selected, '#ffffff']].forEach(function (marked) {
                if (marked[0] === null || marked[0] < 0) { return; }
                ctx.strokeStyle = marked[1];
                ctx.beginPath();
                ctx.arc(xs[marked[0]] * zoom + ox, ys[marked[0]] * zoom + oy, Math.max(radii[marked[0]] * base + 5, 7), 0, Math.PI * 2);
                ctx.stroke();
            });
        }

        function paintZoneNames(zoom, ox, oy) {
            ctx.font = '600 12px sans-serif';
            ctx.textAlign = 'center';
            ctx.lineWidth = 3;
            ctx.strokeStyle = 'rgba(3, 6, 13, 0.85)';
            zones.forEach(function (zone, index) {
                if (zone.kind === 'halo' || Math.sqrt(zone.cells) * cell * zoom / 2 < ZONE_LABEL_RADIUS) { return; }
                ctx.fillStyle = index === nativeZone ? accent : 'rgba(233, 238, 245, 0.75)';
                ctx.strokeText(zone.name, zone.x * zoom + ox, zone.y * zoom + oy);
                ctx.fillText(zone.name, zone.x * zoom + ox, zone.y * zoom + oy);
            });
            ctx.textAlign = 'start';
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
            if ((all && zoom >= 1) || fewMatches) {  // Every name of the whole sector would be a blur
                for (var i = 0; i < count && painted < LABELS_LIMIT; i++) {
                    if (inZone[i] && (!filtering || matched[i]) && label(i)) { painted++; }
                }
            }
            // Once the empires fill a map, far away, their names would hide it
            if (!all && (colonisedRanks.length <= LABELS_MAX_MATCHES || zoom >= LABELS_ABOVE_ZOOM / 3)) {
                colonisedRanks.forEach(function (system) {
                    if (inZone[system] && (!filtering || matched[system])) { label(system); }
                });
            }
            if (selected !== null) { label(selected); }
        }


        ////////////////////////////////////////////////////////////////////////////////////////////////////////////////
        // THE WAYS TO THE ZONES AROUND A QUADRANT : links on the border they share, kept inside the view

        var exits = Array.prototype.map.call(root.querySelectorAll('.qmap-exit'), function (exit) {
            exit.querySelector('.fas').style.transform = 'rotate(' + Math.atan2(+exit.dataset.dy, +exit.dataset.dx) + 'rad)';
            return {element: exit, y: +exit.dataset.y, x: +exit.dataset.x};
        });

        function placeExits(zoom, ox, oy, width, height) {
            exits.forEach(function (exit) {
                var sx = clamp(exit.x * zoom + ox, 20, width - 20), sy = clamp(exit.y * zoom + oy, 20, height - 20);
                exit.element.style.transform = 'translate(' + Math.round(sx) + 'px, ' + Math.round(sy) + 'px)';
            });
        }


        ////////////////////////////////////////////////////////////////////////////////////////////////////////////////
        // COLORS AND LEGEND

        function groupsOf(system) {
            if (state.mode === 'empire') { return ownersOf[system] || []; }
            if (state.mode === 'entente') { return ententesOf[system] || []; }
            return [S.stars[starRanks[system]].key];
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
                colorRanks[i] = ranksOfColor[color];
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
            return S.stars.map(function (star, index) {
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
                if (inZone[i] && (state.mode === 'star' || ownersOf[i])) {
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

        var vortexToggle = byId('qmap-vortex');
        if (vortexToggle) {
            byId('qmap-vortex-count').textContent = links.length / 2;
            vortexToggle.addEventListener('change', function () { state.vortex = vortexToggle.checked; repaint(); });
        }


        ////////////////////////////////////////////////////////////////////////////////////////////////////////////////
        // SEARCH : only the systems of the map itself, never those around a quadrant

        function matches(i) {
            if (!inZone[i]) { return false; }
            if (state.text && names[i].indexOf(state.text) < 0 && (colonyWords[i] || '').indexOf(state.text) < 0 &&
                places[i].indexOf(state.text) !== 0 && seedOf(i).indexOf(state.text) !== 0) { return false; }
            if (state.anyStar && !state.stars[S.stars[starRanks[i]].key]) { return false; }
            if (state.colony) {
                var colonies = coloniesOf[i] || [];
                if (state.colony === 'any' && !colonies.length) { return false; }
                if (state.colony === 'free' && colonies.length) { return false; }
                if (state.colony === 'mine' && !colonies.some(function (colony) { return colony.is_mine; })) { return false; }
                if (state.colony === 'others' && !colonies.some(function (colony) { return !colony.is_mine; })) { return false; }
            }
            if (state.type === '__habitable' && !isHabitable[typeRanks[i]]) { return false; }
            if (state.type && state.type !== '__habitable' && S.types[typeRanks[i]].key !== state.type) { return false; }
            if (resourceValues && (resourceValues[i] === 0 || resourceValues[i] < state.min)) { return false; }
            if (state.anyFocus && !groupsOf(i).some(function (group) { return state.focus[group]; })) { return false; }
            return true;
        }

        function applyFilters() {
            state.anyStar = Object.keys(state.stars).length > 0;
            state.anyFocus = Object.keys(state.focus).length > 0;
            filtering = !!(state.text || state.anyStar || state.colony || state.type || resourceValues || state.anyFocus);
            if (state.text && !names) {
                names = S.name.map(C.normalize);
                places = [];
                for (var p = 0; p < count; p++) { places.push(placeOf(p).toLowerCase()); }
            }

            var found = [];
            zoneMatches.fill(0);
            for (var i = 0; i < count; i++) {
                matched[i] = inZone[i] && (!filtering || matches(i)) ? 1 : 0;
                if (matched[i]) {
                    found.push(i);
                    if (zoneRanks[i] >= 0) { zoneMatches[zoneRanks[i]] += resourceValues ? resourceValues[i] : 1; }
                }
            }
            zoneMax = zoneMatches.reduce(function (max, value) { return Math.max(max, value); }, 0);
            matchCount = found.length;
            byId('qmap-reset').hidden = !filtering && !state.resource;
            renderResults(found);
            renderZones();
            renderStamps();
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
                el('small', '', starName(system) + ' · ' + placeOf(system), itemNames);
                if (coloniesOf[system]) { icon('fa-city', button); }
                if (resourceValues) { el('span', 'qmap-count', resourceValues[system], button); }
                button.addEventListener('click', function () { select(system, true); });
                button.addEventListener('pointerenter', function () { hovered = system; repaint(); });
                button.addEventListener('pointerleave', function () { hovered = -1; repaint(); });
            });
            if (found.length > C.RESULTS_SHOWN) { el('li', 'qmap-empty', '+ ' + (found.length - C.RESULTS_SHOWN) + ' ' + L.more, list); }
        }

        var resourceSelect = byId('qmap-resource');  // Only on the map of a quadrant : the deposits of the whole sector would be too heavy

        byId('qmap-text').addEventListener('input', function () { clearPreset(); state.text = C.normalize(this.value.trim()); applyFilters(); });
        byId('qmap-colony').addEventListener('change', function () { clearPreset(); state.colony = this.value; applyFilters(); });
        byId('qmap-type').addEventListener('change', function () { clearPreset(); state.type = this.value; applyFilters(); });
        if (resourceSelect) {
            resourceSelect.addEventListener('change', function () { clearPreset(); setResource(this.value); });
            byId('qmap-min').addEventListener('input', function () {
                clearPreset();
                state.min = Number(this.value);
                byId('qmap-min-value').textContent = state.min;
                applyFilters();
            });
        }

        function loadResource(resource) {
            if (loadedResources[resource]) { return Promise.resolve(loadedResources[resource]); }
            return fetch('/api_zone_deposits/?zone=' + data.id + '&resource=' + encodeURIComponent(resource)).then(function (response) {
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
            if (!resourceSelect) {
                applyFilters();
                return;
            }
            resourceSelect.value = resource;
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
            S.types.slice().sort(function (a, b) { return a.name.localeCompare(b.name); }).forEach(function (type) {
                el('option', '', type.name, byId('qmap-type')).value = type.key;
            });
            if (resourceSelect) {
                data.resources.slice().sort(function (a, b) { return a.name.localeCompare(b.name); }).forEach(function (resource) {
                    el('option', '', resource.name, byId(resource.rare ? 'qmap-resources-rare' : 'qmap-resources-common')).value = resource.id;
                });
            }
        })();

        function syncStarChips() {
            root.querySelectorAll('.qmap-chip').forEach(function (chip) {
                chip.setAttribute('aria-pressed', !!state.stars[chip.getAttribute('data-star')]);
            });
        }

        function clearSearch() {
            state.text = ''; state.stars = {}; state.colony = ''; state.type = ''; state.focus = {};
            byId('qmap-text').value = '';
            byId('qmap-colony').value = '';
            byId('qmap-type').value = '';
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
                S.stars.forEach(function (star, index) {
                    if (starInfos[index].size >= C.LARGEST_STAR_SIZE) { state.stars[star.key] = true; }
                });
                syncStarChips();
            },
            colonized: function () { state.colony = 'any'; byId('qmap-colony').value = 'any'; },
            habitable: function () { state.type = '__habitable'; byId('qmap-type').value = '__habitable'; },
            rare: function () { setResource('__rare'); },
            concentration: function () { if (mostAbundant) { setResource(mostAbundant.id, 0.1); } }
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


        ////////////////////////////////////////////////////////////////////////////////////////////////////////////////
        // UNDER THE POINTER

        // The closest system : among the ones the search keeps, or around the quadrant
        function systemAt(x, y) {
            var radius = HIT_RADIUS * mapView.unit();
            var best = -1, bestDistance = radius * radius;
            var rows = [gridCoordinate(y - radius, minY), gridCoordinate(y + radius, minY)];
            var columns = [gridCoordinate(x - radius, minX), gridCoordinate(x + radius, minX)];
            for (var row = rows[0]; row <= rows[1]; row++) {
                for (var col = columns[0]; col <= columns[1]; col++) {
                    for (var i = gridHeads[row * GRID_SIDE + col]; i >= 0; i = gridNext[i]) {
                        var dx = xs[i] - x, dy = ys[i] - y, distance = dx * dx + dy * dy;
                        if (distance < bestDistance && (matched[i] || !inZone[i])) {
                            best = i;
                            bestDistance = distance;
                        }
                    }
                }
            }
            return best;
        }

        function hideTooltip() { tooltip.hidden = true; }

        function setHovered(system, zone) {
            if (system !== hovered || zone !== hoveredZone) {
                var zoneChanged = zone !== hoveredZone;
                hovered = system;
                hoveredZone = zone;
                if (zoneChanged) { renderZones(); }
                repaint();
            }
        }

        canvas.addEventListener('pointermove', function (event) {
            if (mapView.isDragging()) { return; }
            var world = mapView.toWorld(event.clientX, event.clientY);
            var system = systemAt(world.x, world.y);
            var zone = system >= 0 ? -1 : zoneAt(world.x, world.y);
            setHovered(system, zone);

            if (system < 0 && zone < 0) {
                hideTooltip();
                return;
            }
            tooltip.textContent = '';
            if (system >= 0) {
                el('b', '', S.name[system], tooltip);
                el('div', '', starName(system) + ' · ' + placeOf(system), tooltip);
                if (!inZone[system] && zoneRanks[system] >= 0) { el('div', '', L.zone + ' ' + zones[zoneRanks[system]].name, tooltip); }
                if (ownersOf[system]) {
                    el('div', '', ownersOf[system].map(function (owner) { return empiresById[owner].civilisation; }).join(', '), tooltip);
                }
                if (resourceValues && inZone[system]) { el('div', '', resourceName() + ' : ' + resourceValues[system], tooltip); }
            } else {
                el('b', '', zones[zone].name, tooltip);
                el('div', '', zoneSummary(zone), tooltip);
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

        function resourceName() {
            return state.resource === '__rare' ? L.rare_resources : resourceSelect.selectedOptions[0].textContent;
        }

        function zoneSummary(zone) {
            var text = zones[zone].kind_name + ' · ' + zones[zone].systems + ' ' + L.all_systems;
            if (isSector && filtering) { text += ' · ' + (resourceValues ? resourceName() + ' : ' : '') + zoneMatches[zone] + ' ' + (zoneMatches[zone] > 1 ? L.results : L.result); }
            return text;
        }


        ////////////////////////////////////////////////////////////////////////////////////////////////////////////////
        // SELECTED SYSTEM OR ZONE

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

        function resourceRows(deposits, parent) {
            Object.keys(deposits).filter(function (resource) { return resourcesById[resource]; }).sort(function (a, b) {
                return deposits[b] - deposits[a];
            }).forEach(function (resource) {
                var row = el('div', 'qmap-deposit' + (resourcesById[resource].rare ? ' is-rare' : ''), null, parent);
                var name = el('span', '', null, row);
                if (resourcesById[resource].rare) { icon('fa-gem', name).title = L.rare; name.appendChild(document.createTextNode(' ')); }
                name.appendChild(document.createTextNode(resourcesById[resource].name));
                el('b', '', deposits[resource], row);
            });
        }

        function renderBodies(system) {
            var section = el('div', '', null, detail);
            el('h4', 'qmap-section', L.bodies, section);
            var waiting = el('p', 'qmap-empty', '…', section);
            fetch('/api_system_bodies/?system=' + seedOf(system)).then(function (response) {
                if (!response.ok) { throw new Error(response.status); }
                return response.json();
            }).then(function (answer) {
                if (selected !== system) { return; }  // Another one has been selected in the meantime
                waiting.remove();
                answer.bodies.forEach(function (body) {
                    var row = el('details', 'qmap-body', null, section);
                    el('summary', '', body.orbit + '. ' + body.name + ' · ' + (body.subtype && body.orbit ? body.subtype : body.type), row);
                    if (!Object.keys(body.deposits).filter(function (resource) { return resourcesById[resource]; }).length) {
                        el('p', 'qmap-empty', L.no_deposit, row);
                    }
                    resourceRows(body.deposits, row);
                });
            }).catch(function () { waiting.textContent = L.load_error; });
        }

        function renderSystem(system) {
            openDetail(S.name[system], starName(system) + ' · ' + S.types[typeRanks[system]].name);
            var facts = el('dl', 'qmap-facts', null, detail);
            el('dt', '', L.position, facts);
            el('dd', '', placeOf(system), facts);
            linkButton('/geography_system/?system_id=' + seedOf(system), 'fa-sun', L.open_system);
            if (!inZone[system] || isSector) {
                if (zoneRanks[system] >= 0) { linkButton(zoneUrl(zoneRanks[system]), 'fa-map', L.open_zone + ' ' + zones[zoneRanks[system]].name); }
            }

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

            if (degree[system]) {
                el('h4', 'qmap-section', L.vortex + ' · ' + degree[system], detail);
                for (var k = 0; k < links.length; k += 2) {
                    if (links[k] !== system && links[k + 1] !== system) { continue; }
                    (function (target) {
                        var button = el('button', 'qmap-link', null, detail);
                        button.type = 'button';
                        icon('fa-circle-nodes', button).style.color = C.NETWORK_COLORS.alpha;
                        button.appendChild(document.createTextNode(' ' + S.name[target] + (inZone[target] ? '' : ' · ' + L.outside)));
                        button.addEventListener('click', function () { select(target, true); });
                    })(links[k] === system ? links[k + 1] : links[k]);
                }
            }
            if (resourceValues && inZone[system]) {
                el('h4', 'qmap-section', L.deposits, detail);
                var deposit = el('div', 'qmap-deposit', null, detail);
                el('span', '', resourceName(), deposit);
                el('b', '', resourceValues[system], deposit);
            }
            renderBodies(system);
        }

        function select(system, reveal) {
            var zoneChanged = selectedZone !== -1;
            selected = system;
            selectedZone = -1;
            detail.hidden = system === null;
            if (system !== null) {
                renderSystem(system);
                if (reveal) { mapView.reveal(xs[system], ys[system]); }
            }
            if (zoneChanged) { renderZones(); }
            repaint();
        }

        function selectZone(zone) {
            if (zone < 0) {
                select(null);
                return;
            }
            selected = null;
            selectedZone = zone;
            openDetail(zones[zone].name, zoneSummary(zone));
            if (zone === nativeZone) { el('p', 'qmap-empty', L.native, detail); }
            if (zone !== ownZone) { linkButton(zoneUrl(zone), 'fa-map', L.open_zone); }
            renderZones();
            repaint();
        }


        ////////////////////////////////////////////////////////////////////////////////////////////////////////////////

        setMode('star');
        resize();
    }

})();
