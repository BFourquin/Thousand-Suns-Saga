// Interactive map of a quadrant (page /geography_quadrant/).
// Everything is in one SVG : the browser gives the hover and the click on each system, CSS the dimming of the others.
// The list of results is the way to reach the systems with the keyboard or a screen reader.

(function () {
    'use strict';

    var root = document.getElementById('qmap');
    if (!root) { return; }

    var data = JSON.parse(document.getElementById('qmap-data').textContent);
    var L = data.labels;
    var SVG_NS = 'http://www.w3.org/2000/svg';
    var C = window.TSSMap;
    var STARS = C.STARS, UNKNOWN_STAR = C.UNKNOWN_STAR, LARGEST_STAR_SIZE = C.LARGEST_STAR_SIZE, NETWORK_COLORS = C.NETWORK_COLORS;
    var MINE_COLOR = C.MINE_COLOR, OTHER_COLOR = C.OTHER_COLOR, NEUTRAL_COLOR = C.NEUTRAL_COLOR, RESULTS_SHOWN = C.RESULTS_SHOWN;
    var clamp = C.clamp, normalize = C.normalize, el = C.el, icon = C.icon;
    var TERRITORY_RADIUS = 4.5;  // In light years, as the positions
    var LABELS_BELOW_SPAN = 16;  // Every name is shown when the view is narrower
    var LABELS_MAX_MATCHES = 25;

    var scene = document.getElementById('qmap-scene');
    var svg = document.getElementById('qmap-svg');
    var tooltip = document.getElementById('qmap-tooltip');
    var detail = document.getElementById('qmap-detail');

    function byId(id) { return document.getElementById(id); }
    function starOf(system) { return STARS[system.star] || UNKNOWN_STAR; }

    function svgEl(name, attributes, parent) {
        var element = document.createElementNS(SVG_NS, name);
        Object.keys(attributes || {}).forEach(function (key) { element.setAttribute(key, attributes[key]); });
        if (parent) { parent.appendChild(element); }
        return element;
    }


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // DATA

    var systemsById = {};
    var empiresById = {};
    var ententesById = {};
    var resourcesById = {};
    var maxBySource = {};

    C.colorGroups(data.empires, data.ententes, MINE_COLOR);
    data.empires.forEach(function (empire) { empiresById[empire.id] = empire; });
    data.ententes.forEach(function (entente) { ententesById[entente.id] = entente; });
    data.resources.forEach(function (resource) { resourcesById[resource.id] = resource; });

    data.systems.forEach(function (system) {
        systemsById[system.id] = system;
        system.network = data.vortex.nodes[system.id] || null;
        system.links = [];
        system.exits = [];
        system.owners = [];
        system.colonies.forEach(function (colony) {
            if (system.owners.indexOf(colony.owner) < 0) { system.owners.push(colony.owner); }
        });
        system.ententes = [];
        system.owners.forEach(function (owner) {
            empiresById[owner].ententes.forEach(function (entente) {
                if (system.ententes.indexOf(entente) < 0) { system.ententes.push(entente); }
            });
        });
        system.rareTotal = 0;
        // A resource unknown of the configuration of this server is never searched nor displayed
        Object.keys(system.deposits).forEach(function (resource) {
            if (!resourcesById[resource]) { delete system.deposits[resource]; return; }
            maxBySource[resource] = Math.max(maxBySource[resource] || 0, system.deposits[resource]);
            if (resourcesById[resource].rare) { system.rareTotal += system.deposits[resource]; }
        });
        maxBySource.__rare = Math.max(maxBySource.__rare || 0, system.rareTotal);
        var words = [system.name, system.id, system.star_name, system.type_name];
        system.bodies.forEach(function (body) { words.push(body.name); });
        system.colonies.forEach(function (colony) { words.push(colony.name); });
        system.owners.forEach(function (owner) { words.push(empiresById[owner].civilisation, empiresById[owner].commandant); });
        system.search = normalize(words.join(' '));
    });

    data.vortex.links.forEach(function (link) {
        systemsById[link.from].links.push({network: link.network, system: link.to});
        systemsById[link.to].links.push({network: link.network, system: link.from});
    });
    data.vortex.exits.forEach(function (exit) { systemsById[exit.from].exits.push(exit); });


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // STATE

    var state = {
        mode: 'star',
        focus: {},  // Items of the legend isolated by a click
        hiddenNetworks: {},
        highlightedNetwork: null,
        allLabels: false,
        territories: true,
        selected: null,
        text: '', stars: {}, colony: '', type: '', resource: '', min: 0, vortexOnly: false
    };
    var preset = null;

    var worldMinX = data.origin.x, worldMinY = data.origin.y, worldSize = data.size;


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // DRAWING : what never changes

    var defs = svgEl('defs', {}, svg);

    function gradient(id, color) {
        var radial = svgEl('radialGradient', {id: id}, defs);
        svgEl('stop', {offset: '0%', 'stop-color': '#ffffff'}, radial);
        svgEl('stop', {offset: '28%', 'stop-color': color}, radial);
        svgEl('stop', {offset: '48%', 'stop-color': color, 'stop-opacity': 0.35}, radial);
        svgEl('stop', {offset: '100%', 'stop-color': color, 'stop-opacity': 0}, radial);
    }
    function territoryGradient(id, color) {
        var radial = svgEl('radialGradient', {id: id}, defs);
        svgEl('stop', {offset: '0%', 'stop-color': color, 'stop-opacity': 0.55}, radial);
        svgEl('stop', {offset: '100%', 'stop-color': color, 'stop-opacity': 0}, radial);
    }
    Object.keys(STARS).forEach(function (key) { gradient('qmap-star-' + key, STARS[key].color); });
    gradient('qmap-star-unknown', UNKNOWN_STAR.color);
    gradient('qmap-neutral', NEUTRAL_COLOR);
    data.empires.forEach(function (empire) { gradient('qmap-group-empire-' + empire.id, empire.color); territoryGradient('qmap-land-empire-' + empire.id, empire.color); });
    data.ententes.forEach(function (entente) { gradient('qmap-group-entente-' + entente.id, entente.color); territoryGradient('qmap-land-entente-' + entente.id, entente.color); });

    var gridLayer = svgEl('g', {'class': 'qmap-grid'}, svg);
    var gridLabels = [];
    for (var step = 0; step <= worldSize; step += 10) {
        svgEl('line', {x1: worldMinX + step, x2: worldMinX + step, y1: worldMinY, y2: worldMinY + worldSize}, gridLayer);
        svgEl('line', {x1: worldMinX, x2: worldMinX + worldSize, y1: worldMinY + step, y2: worldMinY + step}, gridLayer);
        gridLabels.push({x: worldMinX + step, y: worldMinY, element: svgText(gridLayer, worldMinX + step)});
        gridLabels.push({x: worldMinX, y: worldMinY + step, element: svgText(gridLayer, worldMinY + step)});
    }
    function svgText(parent, text) {
        var element = svgEl('text', {}, parent);
        element.textContent = text;
        return element;
    }

    var territoryLayer = svgEl('g', {'class': 'qmap-territories'}, svg);
    var vortexLayer = svgEl('g', {'class': 'qmap-vortex'}, svg);
    var systemsLayer = svgEl('g', {'class': 'qmap-systems'}, svg);

    var vortexLines = [];
    data.vortex.links.forEach(function (link) {
        var from = systemsById[link.from], to = systemsById[link.to];
        vortexLines.push({
            network: link.network,
            element: svgEl('line', {x1: from.x, y1: from.y, x2: to.x, y2: to.y, stroke: NETWORK_COLORS[link.network], 'data-network': link.network}, vortexLayer)
        });
    });
    data.vortex.exits.forEach(function (exit) {
        var from = systemsById[exit.from];
        var border = {
            north: {x: from.x, y: worldMinY}, south: {x: from.x, y: worldMinY + worldSize},
            west: {x: worldMinX, y: from.y}, east: {x: worldMinX + worldSize, y: from.y}
        }[exit.direction];
        vortexLines.push({
            network: exit.network,
            element: svgEl('line', {x1: from.x, y1: from.y, x2: border.x, y2: border.y, stroke: NETWORK_COLORS[exit.network], 'class': 'is-exit', 'data-network': exit.network}, vortexLayer)
        });
    });

    data.systems.forEach(function (system) {
        var group = svgEl('g', {'class': 'qmap-sys', 'data-id': system.id}, systemsLayer);
        svgEl('circle', {'class': 'qmap-hit', r: 9}, group);  // Enough room for a finger on the smallest stars
        system.radius = 2.2 + 2.4 * starOf(system).size;
        system.node = system.network ? svgEl('circle', {'class': 'qmap-node', r: system.radius + 3.2, stroke: NETWORK_COLORS[system.network]}, group) : null;
        system.rings = svgEl('g', {'class': 'qmap-rings'}, group);
        system.starCircle = svgEl('circle', {'class': 'qmap-star', r: system.radius * 2.1}, group);
        system.marker = svgEl('circle', {'class': 'qmap-mark', r: system.radius + 6}, group);
        system.labelElement = svgText(group, system.name);
        system.labelElement.setAttribute('class', 'qmap-name');
        system.labelElement.setAttribute('x', system.radius + 5);
        system.labelElement.setAttribute('y', 3.5);
        system.element = group;
    });


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // VIEW : pan and zoom

    var mapView = C.createView({
        scene: scene, minX: worldMinX, minY: worldMinY, size: worldSize, apply: applyView, dragStart: hideTooltip,
        click: function (event) {
            var marker = event.target.closest('.qmap-sys');
            select(marker ? systemsById[marker.getAttribute('data-id')] : null);
        },
        escape: function () { select(null); }
    });
    var view = mapView.view;

    function applyView() {
        var unit = mapView.unit();
        var width = mapView.width() * unit, height = mapView.height() * unit;
        svg.setAttribute('viewBox', (view.cx - width / 2) + ' ' + (view.cy - height / 2) + ' ' + width + ' ' + height);

        // The stars grow slower than the map : the markers stay readable and the systems get apart
        var scale = unit * Math.pow(worldSize / view.span, 0.3);
        data.systems.forEach(function (system) {
            system.element.setAttribute('transform', 'translate(' + system.x + ' ' + system.y + ') scale(' + scale * (system.emphasis || 1) + ')');
        });
        gridLabels.forEach(function (label) {
            label.element.setAttribute('transform', 'translate(' + label.x + ' ' + label.y + ') scale(' + unit + ')');
        });
        applyLabels();
    }

    function applyLabels() {
        var fewMatches = isFiltering() && matchCount <= LABELS_MAX_MATCHES;
        var close = view.span < LABELS_BELOW_SPAN;
        data.systems.forEach(function (system) {
            var show = state.allLabels || close || system === state.selected || system.colonies.length > 0 || (fewMatches && system.matches);
            system.labelElement.style.display = show ? '' : 'none';
        });
    }

    root.querySelector('.qmap-controls').addEventListener('click', function (event) {
        var button = event.target.closest('button');
        if (!button) { return; }
        var action = button.getAttribute('data-action');
        if (action === 'labels') {
            state.allLabels = !state.allLabels;
            button.setAttribute('aria-pressed', state.allLabels);
            applyLabels();
        }
        if (action === 'territories') {
            state.territories = !state.territories;
            button.setAttribute('aria-pressed', state.territories);
            territoryLayer.style.display = state.territories ? '' : 'none';
        }
    });


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // COLORS AND LEGEND

    function groupsOf(system) {
        if (state.mode === 'empire') { return system.owners; }
        if (state.mode === 'entente') { return system.ententes; }
        return [system.star];
    }

    function colorOfGroup(group) {
        if (state.mode === 'empire') { return empiresById[group].color; }
        if (state.mode === 'entente') { return ententesById[group].color; }
        return (STARS[group] || UNKNOWN_STAR).color;
    }

    function ringsOf(system) {
        // A system shared between several groups gets a ring with one arc for each of them
        if (state.mode !== 'star') { return groupsOf(system).map(colorOfGroup); }
        var colors = [];
        if (system.colonies.some(function (colony) { return colony.is_mine; })) { colors.push(MINE_COLOR); }
        if (system.colonies.some(function (colony) { return !colony.is_mine; })) { colors.push(OTHER_COLOR); }
        return colors;
    }

    function applyColors() {
        territoryLayer.textContent = '';
        data.systems.forEach(function (system) {
            var groups = groupsOf(system);
            var fill;
            if (state.mode === 'star') {
                fill = 'url(#qmap-star-' + (STARS[system.star] ? system.star : 'unknown') + ')';
            } else if (groups.length) {
                fill = 'url(#qmap-group-' + state.mode + '-' + groups[0] + ')';
            } else {
                fill = 'url(#qmap-neutral)';
            }
            system.starCircle.setAttribute('fill', fill);
            system.element.classList.toggle('is-neutral', state.mode !== 'star' && !groups.length);

            system.rings.textContent = '';
            var colors = ringsOf(system);
            colors.forEach(function (color, index) {
                var ring = svgEl('circle', {'class': 'qmap-ring', r: system.radius + 2, stroke: color}, system.rings);
                if (colors.length > 1) {
                    // Every arc takes its share of a circle measured as 'colors.length' long
                    ring.setAttribute('pathLength', colors.length);
                    ring.setAttribute('stroke-dasharray', '1 ' + (colors.length - 1));
                    ring.setAttribute('stroke-dashoffset', -index);
                }
            });

            if (state.mode !== 'star') {
                groups.forEach(function (group) {
                    svgEl('circle', {cx: system.x, cy: system.y, r: TERRITORY_RADIUS, fill: 'url(#qmap-land-' + state.mode + '-' + group + ')', 'data-group': group}, territoryLayer);
                });
            }
        });
    }

    function legendItems() {
        if (state.mode === 'empire') {
            return data.empires.map(function (empire) {
                return {key: empire.id, name: empire.civilisation, detail: empire.commandant, color: empire.color};
            });
        }
        if (state.mode === 'entente') {
            return data.ententes.map(function (entente) { return {key: entente.id, name: entente.name, color: entente.color}; });
        }
        var present = {};
        data.systems.forEach(function (system) { present[system.star] = system.star_name; });
        return Object.keys(present).sort(function (a, b) {
            return (STARS[b] || UNKNOWN_STAR).size - (STARS[a] || UNKNOWN_STAR).size;
        }).map(function (star) { return {key: star, name: present[star], color: (STARS[star] || UNKNOWN_STAR).color}; });
    }

    function renderLegend() {
        var list = byId('qmap-legend');
        list.textContent = '';
        var items = legendItems();
        if (!items.length) {
            el('li', 'qmap-empty', state.mode === 'empire' ? L.no_empire : L.no_entente, list);
            return;
        }
        items.forEach(function (item) {
            var count = data.systems.filter(function (system) { return groupsOf(system).indexOf(item.key) >= 0; }).length;
            var button = el('button', 'qmap-legend-item', null, el('li', '', null, list));
            button.type = 'button';
            button.setAttribute('aria-pressed', !!state.focus[item.key]);
            var dot = el('span', 'qmap-dot', null, button);
            dot.style.background = item.color;
            var names = el('span', 'qmap-legend-name', item.name, button);
            if (item.detail) { el('small', '', item.detail, names); }
            el('span', 'qmap-count', count, button);
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
        root.classList.toggle('is-group-mode', mode !== 'star');
        applyColors();
        renderLegend();
        applyFilters();
    }

    root.querySelectorAll('[data-mode]').forEach(function (button) {
        button.addEventListener('click', function () { setMode(button.getAttribute('data-mode')); });
    });


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // VORTEX NETWORKS

    function applyNetworks() {
        vortexLines.forEach(function (line) {
            var hidden = !!state.hiddenNetworks[line.network];
            line.element.style.display = hidden ? 'none' : '';
            line.element.classList.toggle('is-highlighted', state.highlightedNetwork === line.network);
            line.element.classList.toggle('is-faded', !!state.highlightedNetwork && state.highlightedNetwork !== line.network);
        });
        data.systems.forEach(function (system) {
            if (system.node) { system.node.style.display = state.hiddenNetworks[system.network] ? 'none' : ''; }
            system.element.classList.toggle('is-in-network', !!state.highlightedNetwork && system.network === state.highlightedNetwork);
        });
    }

    (function renderNetworks() {
        var counts = {};
        Object.keys(data.vortex.nodes).forEach(function (id) { counts[data.vortex.nodes[id]] = (counts[data.vortex.nodes[id]] || 0) + 1; });
        var list = byId('qmap-networks');
        var names = Object.keys(counts).sort();
        if (!names.length) { el('li', 'qmap-empty', L.no_vortex, list); }
        names.forEach(function (network) {
            var row = el('label', 'qmap-network', null, el('li', '', null, list));
            var input = el('input', '', null, row);
            input.type = 'checkbox';
            input.checked = true;
            var dot = el('span', 'qmap-dot', null, row);
            dot.style.background = NETWORK_COLORS[network];
            el('span', 'qmap-legend-name', L.network + ' ' + L[network], row);
            el('span', 'qmap-count', counts[network], row);
            input.addEventListener('change', function () {
                if (input.checked) { delete state.hiddenNetworks[network]; } else { state.hiddenNetworks[network] = true; }
                applyNetworks();
            });
            row.addEventListener('pointerenter', function () { state.highlightedNetwork = network; applyNetworks(); });
            row.addEventListener('pointerleave', function () { state.highlightedNetwork = null; applyNetworks(); });
        });
    })();


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // SEARCH

    var matchCount = 0;

    function isFiltering() {
        return !!(state.text || Object.keys(state.stars).length || state.colony || state.type || state.resource || state.vortexOnly || Object.keys(state.focus).length);
    }

    function resourceValue(system, resource) {
        return resource === '__rare' ? system.rareTotal : (system.deposits[resource] || 0);
    }

    function matches(system) {
        if (state.text && system.search.indexOf(state.text) < 0) { return false; }
        if (Object.keys(state.stars).length && !state.stars[system.star]) { return false; }
        if (state.colony === 'any' && !system.colonies.length) { return false; }
        if (state.colony === 'free' && system.colonies.length) { return false; }
        if (state.colony === 'mine' && !system.colonies.some(function (colony) { return colony.is_mine; })) { return false; }
        if (state.colony === 'others' && !system.colonies.some(function (colony) { return !colony.is_mine; })) { return false; }
        if (state.type === '__habitable' && !/habitable|native/.test(system.type)) { return false; }
        if (state.type && state.type !== '__habitable' && system.type !== state.type) { return false; }
        if (state.resource && (resourceValue(system, state.resource) === 0 || resourceValue(system, state.resource) < state.min)) { return false; }
        if (state.vortexOnly && !system.network) { return false; }
        if (Object.keys(state.focus).length && !groupsOf(system).some(function (group) { return state.focus[group]; })) { return false; }
        return true;
    }

    function compareResults(a, b) {
        if (state.resource) { return resourceValue(b, state.resource) - resourceValue(a, state.resource); }
        return starOf(b).size - starOf(a).size || a.name.localeCompare(b.name);
    }

    function applyFilters() {
        var filtering = isFiltering();
        var maxValue = state.resource ? (maxBySource[state.resource] || 1) : 1;
        var found = [];
        data.systems.forEach(function (system) {
            system.matches = matches(system);
            if (system.matches) { found.push(system); }
            system.element.classList.toggle('is-dim', filtering && !system.matches);
            system.element.classList.toggle('is-match', filtering && system.matches);
            // The richer the system, the bigger its marker
            system.emphasis = state.resource && system.matches ? 1 + 0.9 * resourceValue(system, state.resource) / maxValue : 1;
        });
        territoryLayer.querySelectorAll('circle').forEach(function (circle) {
            var focused = !Object.keys(state.focus).length || state.focus[circle.getAttribute('data-group')];
            circle.style.opacity = focused ? '' : 0.1;
        });
        matchCount = found.length;
        vortexLayer.classList.toggle('is-receding', filtering && !state.vortexOnly);
        byId('qmap-reset').hidden = !filtering;
        renderResults(found.sort(compareResults), filtering);
        applyView();
    }

    function renderResults(found, filtering) {
        byId('qmap-count').textContent = filtering
            ? (found.length ? found.length + ' ' + (found.length > 1 ? L.results : L.result) : L.no_result)
            : found.length + ' ' + L.all_systems;
        var list = byId('qmap-results');
        list.textContent = '';
        found.slice(0, RESULTS_SHOWN).forEach(function (system) {
            var button = el('button', 'qmap-result', null, el('li', '', null, list));
            button.type = 'button';
            var dot = el('span', 'qmap-dot', null, button);
            dot.style.background = starOf(system).color;
            var names = el('span', 'qmap-legend-name', system.name, button);
            el('small', '', system.star_name + ' · ' + system.y + ' / ' + system.x, names);
            if (system.colonies.length) { icon('fa-city', button); }
            if (system.network) { icon('fa-circle-nodes', button).style.color = NETWORK_COLORS[system.network]; }
            if (state.resource) { el('span', 'qmap-count', resourceValue(system, state.resource), button); }
            button.addEventListener('click', function () { select(system, true); });
            button.addEventListener('pointerenter', function () { system.element.classList.add('is-hover'); });
            button.addEventListener('pointerleave', function () { system.element.classList.remove('is-hover'); });
        });
        if (found.length > RESULTS_SHOWN) { el('li', 'qmap-empty', '+ ' + (found.length - RESULTS_SHOWN) + ' ' + L.more, list); }
    }

    // Controls : each one changes one field of the state
    byId('qmap-text').addEventListener('input', function () { clearPreset(); state.text = normalize(this.value.trim()); applyFilters(); });
    byId('qmap-colony').addEventListener('change', function () { clearPreset(); state.colony = this.value; applyFilters(); });
    byId('qmap-type').addEventListener('change', function () { clearPreset(); state.type = this.value; applyFilters(); });
    byId('qmap-vortex-only').addEventListener('change', function () { clearPreset(); state.vortexOnly = this.checked; applyFilters(); });
    byId('qmap-resource').addEventListener('change', function () { clearPreset(); setResource(this.value, 0); });
    byId('qmap-min').addEventListener('input', function () {
        clearPreset();
        state.min = Number(this.value);
        byId('qmap-min-value').textContent = state.min;
        applyFilters();
    });

    function setResource(resource, min) {
        state.resource = resource;
        state.min = min;
        byId('qmap-resource').value = resource;
        byId('qmap-range').hidden = !resource;
        var range = byId('qmap-min');
        range.max = maxBySource[resource] || 100;
        range.value = min;
        byId('qmap-min-value').textContent = min;
        applyFilters();
    }

    (function fillSearchOptions() {
        var stars = byId('qmap-stars');
        var present = {};
        data.systems.forEach(function (system) { present[system.star] = system.star_name; });
        Object.keys(present).sort(function (a, b) { return (STARS[b] || UNKNOWN_STAR).size - (STARS[a] || UNKNOWN_STAR).size; }).forEach(function (star) {
            var chip = el('button', 'qmap-chip', null, stars);
            chip.type = 'button';
            chip.setAttribute('aria-pressed', false);
            chip.setAttribute('data-star', star);
            el('span', 'qmap-dot', null, chip).style.background = (STARS[star] || UNKNOWN_STAR).color;
            chip.appendChild(document.createTextNode(present[star]));
            chip.addEventListener('click', function () {
                clearPreset();
                if (state.stars[star]) { delete state.stars[star]; } else { state.stars[star] = true; }
                syncStarChips();
                applyFilters();
            });
        });

        var types = {};
        data.systems.forEach(function (system) { types[system.type] = system.type_name; });
        Object.keys(types).sort(function (a, b) { return types[a].localeCompare(types[b]); }).forEach(function (type) {
            var option = el('option', '', types[type], byId('qmap-type'));
            option.value = type;
        });

        data.resources.slice().sort(function (a, b) { return a.name.localeCompare(b.name); }).forEach(function (resource) {
            var option = el('option', '', resource.name, byId(resource.rare ? 'qmap-resources-rare' : 'qmap-resources-common'));
            option.value = resource.id;
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
        setResource('', 0);
    }

    function clearPreset() {
        preset = null;
        root.querySelectorAll('[data-preset]').forEach(function (button) { button.setAttribute('aria-pressed', false); });
    }

    // The most abundant common resource, and the value only the richest tenth of its systems reach
    function bestConcentration() {
        var totals = {};
        data.systems.forEach(function (system) {
            Object.keys(system.deposits).forEach(function (resource) {
                if (!resourcesById[resource].rare) { totals[resource] = (totals[resource] || 0) + system.deposits[resource]; }
            });
        });
        var best = Object.keys(totals).sort(function (a, b) { return totals[b] - totals[a]; })[0];
        if (!best) { return {resource: '', min: 0}; }
        var values = data.systems.map(function (system) { return system.deposits[best] || 0; }).filter(Boolean).sort(function (a, b) { return a - b; });
        return {resource: best, min: values[Math.floor(values.length * 0.9)]};
    }

    var PRESETS = {
        largest: function () {
            Object.keys(STARS).forEach(function (star) { if (STARS[star].size >= LARGEST_STAR_SIZE) { state.stars[star] = true; } });
            syncStarChips();
        },
        colonized: function () { state.colony = 'any'; byId('qmap-colony').value = 'any'; },
        habitable: function () { state.type = '__habitable'; byId('qmap-type').value = '__habitable'; },
        rare: function () { setResource('__rare', 0); },
        concentration: function () {
            var best = bestConcentration();
            setResource(best.resource, best.min);
        },
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
    // TOOLTIP

    var hoveredNetwork = null;

    function hideTooltip() { tooltip.hidden = true; }

    svg.addEventListener('pointermove', function (event) {
        if (mapView.isDragging()) { return; }
        var marker = event.target.closest('.qmap-sys');
        if (!marker) {
            hideTooltip();
            if (hoveredNetwork) { hoveredNetwork = null; state.highlightedNetwork = null; applyNetworks(); }
            return;
        }
        var system = systemsById[marker.getAttribute('data-id')];
        tooltip.textContent = '';
        el('b', '', system.name, tooltip);
        el('div', '', system.star_name + ' · ' + system.y + ' / ' + system.x, tooltip);
        if (system.owners.length) {
            el('div', '', system.owners.map(function (owner) { return empiresById[owner].civilisation; }).join(', '), tooltip);
        }
        if (system.network) { el('div', '', L.network + ' ' + L[system.network], tooltip).style.color = NETWORK_COLORS[system.network]; }
        if (state.resource && state.resource !== '__rare' && resourcesById[state.resource]) {
            el('div', '', resourcesById[state.resource].name + ' : ' + resourceValue(system, state.resource), tooltip);
        }
        tooltip.hidden = false;
        var rect = scene.getBoundingClientRect();
        var x = event.clientX - rect.left, y = event.clientY - rect.top;
        tooltip.style.left = Math.min(x + 14, rect.width - tooltip.offsetWidth - 8) + 'px';
        tooltip.style.top = Math.min(y + 14, rect.height - tooltip.offsetHeight - 8) + 'px';

        if (system.network !== hoveredNetwork) {
            hoveredNetwork = system.network;
            state.highlightedNetwork = system.network;
            applyNetworks();
        }
    });

    svg.addEventListener('pointerleave', function () {
        hideTooltip();
        if (hoveredNetwork) { hoveredNetwork = null; state.highlightedNetwork = null; applyNetworks(); }
    });


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // SELECTED SYSTEM

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

    function renderDetail(system) {
        detail.textContent = '';
        detail.hidden = !system;
        if (!system) { return; }

        var close = el('button', 'qmap-detail-close', null, detail);
        close.type = 'button';
        close.setAttribute('aria-label', '×');
        icon('fa-xmark', close);
        close.addEventListener('click', function () { select(null); });

        el('h3', 'qmap-detail-name', system.name, detail);
        el('p', 'qmap-detail-kind', system.star_name + ' · ' + system.type_name, detail);
        var facts = el('dl', 'qmap-facts', null, detail);
        el('dt', '', L.position, facts);
        el('dd', '', system.y + ' / ' + system.x, facts);
        var open = el('a', 'btn btn-default btn-sm btn-block', null, detail);
        open.href = '/geography_system/?system_id=' + system.id;
        icon('fa-sun', open);
        open.appendChild(document.createTextNode(' ' + L.open_system));

        el('h4', 'qmap-section', L.colonies, detail);
        if (!system.colonies.length) { el('p', 'qmap-empty', L.no_colony, detail); }
        system.colonies.forEach(function (colony) {
            var row = el('div', 'qmap-colony', null, detail);
            el('span', 'qmap-dot', null, row).style.background = empiresById[colony.owner].color;
            var names = el('span', 'qmap-legend-name', null, row);
            if (colony.id) {
                var link = el('a', '', colony.name, names);
                link.href = '/colony/?colony_id=' + colony.id;
            } else {
                names.appendChild(document.createTextNode(colony.name));
            }
            el('small', '', empiresById[colony.owner].civilisation + ' · ' + empiresById[colony.owner].commandant, names);
            empiresById[colony.owner].ententes.forEach(function (entente) {
                var ententeLink = el('a', 'qmap-entente', ententesById[entente].name, names);
                ententeLink.href = '/entente/?entente_id=' + entente;
            });
        });

        if (system.network) {
            el('h4', 'qmap-section', L.vortex + ' · ' + L.network + ' ' + L[system.network], detail);
            system.links.forEach(function (link) {
                var target = systemsById[link.system];
                var button = el('button', 'qmap-link', null, detail);
                button.type = 'button';
                icon('fa-circle-nodes', button).style.color = NETWORK_COLORS[link.network];
                button.appendChild(document.createTextNode(' ' + target.name));
                button.addEventListener('click', function () { select(target, true); });
            });
            system.exits.forEach(function (exit) {
                var anchor = el('a', 'qmap-link', null, detail);
                anchor.href = '/geography_quadrant/?quadrant=' + exit.quadrant;
                icon('fa-arrow-right-from-bracket', anchor).style.color = NETWORK_COLORS[exit.network];
                anchor.appendChild(document.createTextNode(' ' + L.open_quadrant));
            });
        }

        el('h4', 'qmap-section', L.deposits, detail);
        if (!Object.keys(system.deposits).length) { el('p', 'qmap-empty', L.no_deposit, detail); }
        resourceRows(system.deposits, detail);

        el('h4', 'qmap-section', L.bodies, detail);
        system.bodies.forEach(function (body) {
            var row = el('details', 'qmap-body', null, detail);
            el('summary', '', body.orbit + '. ' + body.name + ' · ' + (body.subtype && body.orbit ? body.subtype : body.type), row);
            if (!Object.keys(body.deposits).length) { el('p', 'qmap-empty', L.no_deposit, row); }
            resourceRows(body.deposits, row);
        });
    }

    function select(system, reveal) {
        if (state.selected) { state.selected.element.classList.remove('is-selected'); }
        state.selected = system;
        if (system) {
            system.element.classList.add('is-selected');
            // Above its neighbours
            systemsLayer.appendChild(system.element);
            if (reveal) { mapView.reveal(system.x, system.y); }
        }
        renderDetail(system);
        applyLabels();
    }


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

    setMode('star');
    applyNetworks();

})();
