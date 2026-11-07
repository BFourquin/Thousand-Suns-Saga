// What the maps of a quadrant and of a sector share : palettes, helpers, and the pan and zoom of their scene.

window.TSSMap = (function () {
    'use strict';

    var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
    function normalize(text) { return String(text).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }

    // Player names only go through textContent
    function el(name, className, text, parent) {
        var element = document.createElement(name);
        if (className) { element.className = className; }
        if (text !== undefined && text !== null) { element.textContent = text; }
        if (parent) { parent.appendChild(element); }
        return element;
    }

    function icon(name, parent) { return el('i', 'fas ' + name, null, parent); }

    function colorGroups(empires, ententes, mineColor) {
        // The golden angle keeps two neighbours of the list far apart on the color wheel
        empires.forEach(function (empire, index) {
            empire.color = empire.is_mine ? mineColor : 'hsl(' + Math.round((30 + index * 137.5) % 360) + ', 85%, 62%)';
        });
        ententes.forEach(function (entente, index) {
            entente.color = 'hsl(' + Math.round((200 + index * 137.5) % 360) + ', 80%, 64%)';
        });
    }

    // options : scene, minX, minY, size of the world, apply() after each move, click(event), dragStart(), escape()
    function createView(options) {
        var scene = options.scene;
        var view = {cx: options.minX + options.size / 2, cy: options.minY + options.size / 2, span: options.size * 1.04};
        var minSpan = 3, maxSpan = options.size * 1.2;
        var width = scene.clientWidth || 1, height = scene.clientHeight || 1, tween = null;

        function unit() { return view.span / Math.min(width, height); }

        function apply() {
            view.span = clamp(view.span, minSpan, maxSpan);
            view.cx = clamp(view.cx, options.minX, options.minX + options.size);
            view.cy = clamp(view.cy, options.minY, options.minY + options.size);
            options.apply();
        }

        function animateTo(cx, cy, span) {
            cancelAnimationFrame(tween);
            if (reducedMotion) {
                view.cx = cx; view.cy = cy; view.span = span;
                apply();
                return;
            }
            var start = {cx: view.cx, cy: view.cy, span: view.span};
            var startTime = performance.now();
            (function frame(now) {
                var t = clamp((now - startTime) / 260, 0, 1);
                var eased = t * t * (3 - 2 * t);
                view.cx = start.cx + (cx - start.cx) * eased;
                view.cy = start.cy + (cy - start.cy) * eased;
                view.span = start.span * Math.pow(span / start.span, eased);
                apply();
                if (t < 1) { tween = requestAnimationFrame(frame); }
            })(startTime);
        }

        function reset() { animateTo(options.minX + options.size / 2, options.minY + options.size / 2, options.size * 1.04); }

        function toWorld(clientX, clientY) {
            var rect = scene.getBoundingClientRect();
            return {x: view.cx + (clientX - rect.left - width / 2) * unit(), y: view.cy + (clientY - rect.top - height / 2) * unit()};
        }

        function zoomAt(factor, clientX, clientY) {
            var world = toWorld(clientX, clientY);
            var span = clamp(view.span * factor, minSpan, maxSpan);
            var applied = span / view.span;
            view.cx = world.x + (view.cx - world.x) * applied;
            view.cy = world.y + (view.cy - world.y) * applied;
            view.span = span;
            apply();
        }

        function zoomCentered(factor) { animateTo(view.cx, view.cy, clamp(view.span * factor, minSpan, maxSpan)); }

        function reveal(x, y) {
            var dx = Math.abs(x - view.cx) / unit(), dy = Math.abs(y - view.cy) / unit();
            if (dx > width / 2 - 90 || dy > height / 2 - 70) { animateTo(x, y, view.span); }
        }

        new ResizeObserver(function () {
            width = scene.clientWidth || 1;
            height = scene.clientHeight || 1;
            apply();
        }).observe(scene);

        scene.addEventListener('wheel', function (event) {
            if (event.target.closest('.qmap-detail')) { return; }
            event.preventDefault();
            cancelAnimationFrame(tween);
            zoomAt(Math.pow(1.0018, event.deltaY), event.clientX, event.clientY);
        }, {passive: false});

        // One finger or the mouse moves the map, two fingers zoom
        var pointers = {}, dragged = false, downAt = null, pinchDistance = null;

        scene.addEventListener('pointerdown', function (event) {
            if (event.target.closest('a, button, .qmap-detail')) { return; }
            pointers[event.pointerId] = {x: event.clientX, y: event.clientY};
            downAt = {x: event.clientX, y: event.clientY};
            dragged = false;
            pinchDistance = null;
        });

        scene.addEventListener('pointermove', function (event) {
            var pointer = pointers[event.pointerId];
            if (!pointer) { return; }
            var list = Object.keys(pointers).map(function (id) { return pointers[id]; });

            if (list.length === 2) {
                pointer.x = event.clientX; pointer.y = event.clientY;
                var distance = Math.hypot(list[0].x - list[1].x, list[0].y - list[1].y);
                if (pinchDistance) { zoomAt(pinchDistance / distance, (list[0].x + list[1].x) / 2, (list[0].y + list[1].y) / 2); }
                pinchDistance = distance;
                dragged = true;
                return;
            }

            if (!dragged && Math.hypot(event.clientX - downAt.x, event.clientY - downAt.y) > 4) {
                dragged = true;
                cancelAnimationFrame(tween);
                scene.setPointerCapture(event.pointerId);
                scene.classList.add('is-dragging');
                options.dragStart();
            }
            if (dragged) {
                view.cx -= (event.clientX - pointer.x) * unit();
                view.cy -= (event.clientY - pointer.y) * unit();
                apply();
            }
            pointer.x = event.clientX; pointer.y = event.clientY;
        });

        function pointerEnd(event) {
            delete pointers[event.pointerId];
            pinchDistance = null;
            scene.classList.remove('is-dragging');
        }
        scene.addEventListener('pointerup', pointerEnd);
        scene.addEventListener('pointercancel', pointerEnd);

        scene.addEventListener('click', function (event) {
            if (dragged) { dragged = false; return; }
            if (event.target.closest('a, button, .qmap-detail')) { return; }
            options.click(event);
        });

        scene.addEventListener('dblclick', function (event) {
            if (event.target.closest('a, button, .qmap-detail')) { return; }
            cancelAnimationFrame(tween);
            zoomAt(0.5, event.clientX, event.clientY);
        });

        scene.addEventListener('keydown', function (event) {
            if (event.target !== scene) { return; }
            var move = view.span * 0.12;
            var actions = {
                ArrowLeft: function () { animateTo(view.cx - move, view.cy, view.span); },
                ArrowRight: function () { animateTo(view.cx + move, view.cy, view.span); },
                ArrowUp: function () { animateTo(view.cx, view.cy - move, view.span); },
                ArrowDown: function () { animateTo(view.cx, view.cy + move, view.span); },
                '+': function () { zoomCentered(0.7); },
                '=': function () { zoomCentered(0.7); },
                '-': function () { zoomCentered(1.4); },
                '0': reset,
                Escape: options.escape
            };
            if (actions[event.key]) { event.preventDefault(); actions[event.key](); }
        });

        scene.querySelector('.qmap-controls').addEventListener('click', function (event) {
            var button = event.target.closest('button');
            var action = button && button.getAttribute('data-action');
            if (action === 'zoom-in') { zoomCentered(0.65); }
            if (action === 'zoom-out') { zoomCentered(1.5); }
            if (action === 'reset') { reset(); }
        });

        return {
            view: view, unit: unit, toWorld: toWorld, reveal: reveal,
            width: function () { return width; }, height: function () { return height; },
            isDragging: function () { return dragged; }
        };
    }

    return {
        // Same palette and same proportions as the orbital view of a system (system_map.css, system_map.js)
        STARS: {
            supergiant: {size: 2.6, color: '#ff5f35'}, giant: {size: 2, color: '#ff8a3c'}, O: {size: 1.55, color: '#8db4ff'},
            wolf_rayet: {size: 1.45, color: '#6fe3ff'}, B: {size: 1.35, color: '#a9c8ff'}, A: {size: 1.2, color: '#dbe7ff'},
            F: {size: 1.1, color: '#fff0b8'}, G: {size: 1, color: '#ffc95c'}, K: {size: 0.9, color: '#ffa94d'}, supernova: {size: 1.8, color: '#fffbe0'},
            nebula: {size: 0.8, color: '#e58cff'}, M: {size: 0.75, color: '#ff7a3d'}, pulsar: {size: 0.6, color: '#7ff5e0'},
            magnetar: {size: 0.6, color: '#ff6fd8'}, neutron: {size: 0.5, color: '#b8f0ff'}, black_hole: {size: 0.5, color: '#8a6fe8'},
            white_dwarf: {size: 0.4, color: '#e6f0ff'}
        },
        UNKNOWN_STAR: {size: 0.7, color: '#8896a8'},
        LARGEST_STAR_SIZE: 1.45,
        NETWORK_COLORS: {alpha: '#4fd8ff', beta: '#ff6fb0', gamma: '#b6ff5c', delta: '#c58bff'},
        MINE_COLOR: '#3ddc97', OTHER_COLOR: '#ffb020', NEUTRAL_COLOR: '#5d6a7c',
        RESULTS_SHOWN: 100,
        clamp: clamp, normalize: normalize, el: el, icon: icon, colorGroups: colorGroups, createView: createView
    };
})();
