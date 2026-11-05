// Orbital view of a solar system (page /geography_system/).
// Everything is painted on one canvas, so that bodies can pass in front of or behind the star and be lit by it.
// Transparent buttons follow the bodies : they stay clickable, reachable with the keyboard and readable by screen readers.

(function () {
    'use strict';

    var root = document.getElementById('sysmap');
    if (!root) { return; }

    var scene = root.querySelector('.sysmap-scene');
    var canvas = root.querySelector('.sysmap-canvas');
    var panel = root.querySelector('.sysmap-panel');
    var ctx = canvas.getContext('2d');
    var cssVars = getComputedStyle(root);
    var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    var STAR_RADIUS = {O: 1.55, B: 1.35, A: 1.2, F: 1.1, G: 1, K: 0.9, M: 0.75, giant: 2, supergiant: 2.6, white_dwarf: 0.4, wolf_rayet: 1.45, nebula: 0.8};
    var BODY_RADIUS = {telluric: 0.52, jovian: 1, planetoid: 0.33, asteroid_belt: 0.6, oort_cloud: 0.9};
    var DISC_IN_PICTURE = 0.62;  // The illustrations are a disc taking this share of a black square
    var MIN_ZOOM = 0.6, MAX_ZOOM = 6;
    var DEFAULT_TILT = 1, DEFAULT_YAW = -0.45;

    function color(name) { return cssVars.getPropertyValue(name).trim(); }
    function hexToRgb(hex) {
        var value = parseInt(hex.slice(1), 16);
        return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
    }
    function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
    function rgba(rgb, alpha) { return 'rgba(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ',' + alpha + ')'; }

    var accent = color('--sys-accent');
    var mineColor = color('--sys-mine');
    var otherColor = color('--sys-other');
    var starColors = {core: hexToRgb(color('--star-core')), mid: hexToRgb(color('--star')), edge: hexToRgb(color('--star-edge'))};


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // PROCEDURAL TEXTURES

    // Same sequence on every visit, so that a system always looks the same
    function seededRandom(seed) {
        return function () {
            seed = (seed * 1664525 + 1013904223) % 4294967296;
            return seed / 4294967296;
        };
    }
    var random = seededRandom(hashString(root.querySelector('.sysmap-detail-name').textContent));

    function hashString(text) {
        var hash = 7;
        for (var i = 0; i < text.length; i++) { hash = (hash * 31 + text.charCodeAt(i)) % 2147483647; }
        return hash;
    }

    function valueNoise(size) {
        var grid = new Float32Array(size * size);
        for (var i = 0; i < grid.length; i++) { grid[i] = random(); }
        function smooth(t) { return t * t * (3 - 2 * t); }
        function at(x, y) {
            var x0 = Math.floor(x), y0 = Math.floor(y);
            var fx = smooth(x - x0), fy = smooth(y - y0);
            function cell(cx, cy) { return grid[((cy % size + size) % size) * size + ((cx % size + size) % size)]; }
            return (cell(x0, y0) * (1 - fx) + cell(x0 + 1, y0) * fx) * (1 - fy) + (cell(x0, y0 + 1) * (1 - fx) + cell(x0 + 1, y0 + 1) * fx) * fy;
        }
        return function fractal(x, y) {
            return (at(x, y) + at(x * 2, y * 2) * 0.5 + at(x * 4, y * 4) * 0.25 + at(x * 8, y * 8) * 0.125) / 1.875;
        };
    }
    var noise = valueNoise(64);

    function makeCanvas(width, height) {
        var sprite = document.createElement('canvas');
        sprite.width = width;
        sprite.height = height || width;
        return sprite;
    }

    function mix(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]; }

    // Turbulent surface of the star, darker near the edge
    function starSurface(offset) {
        var size = 256, sprite = makeCanvas(size), sctx = sprite.getContext('2d');
        var image = sctx.createImageData(size, size);
        for (var y = 0; y < size; y++) {
            for (var x = 0; x < size; x++) {
                var dx = (x - size / 2) / (size / 2), dy = (y - size / 2) / (size / 2), distance = Math.sqrt(dx * dx + dy * dy);
                if (distance > 1) { continue; }
                var limb = Math.sqrt(1 - distance * distance);
                var turbulence = noise(x / 22 + offset, y / 22 + offset);
                var heat = clamp(limb * 0.85 + (turbulence - 0.5) * 1.1, 0, 1);
                var rgb = heat < 0.5 ? mix(starColors.edge, starColors.mid, heat * 2) : mix(starColors.mid, starColors.core, (heat - 0.5) * 2);
                var i = (y * size + x) * 4;
                image.data[i] = rgb[0];
                image.data[i + 1] = rgb[1];
                image.data[i + 2] = rgb[2];
                image.data[i + 3] = clamp((1 - distance) * 60, 0, 1) * 255;
            }
        }
        sctx.putImageData(image, 0, 0);
        return sprite;
    }

    // Corona : light fading away from the star, irregular around it
    function starCorona() {
        var size = 320, sprite = makeCanvas(size), sctx = sprite.getContext('2d');
        var image = sctx.createImageData(size, size);
        for (var y = 0; y < size; y++) {
            for (var x = 0; x < size; x++) {
                var dx = (x - size / 2) / (size / 2), dy = (y - size / 2) / (size / 2), distance = Math.sqrt(dx * dx + dy * dy);
                if (distance >= 1) { continue; }
                var angle = Math.atan2(dy, dx);
                var flares = noise(Math.cos(angle) * 3 + 9, Math.sin(angle) * 3 + 9);
                var light = Math.pow(1 - distance, 2.6) * (0.55 + flares * 1.1);
                var rgb = mix(starColors.edge, starColors.mid, clamp(light * 1.6, 0, 1));
                var i = (y * size + x) * 4;
                image.data[i] = rgb[0];
                image.data[i + 1] = rgb[1];
                image.data[i + 2] = rgb[2];
                image.data[i + 3] = clamp(light, 0, 1) * 255;
            }
        }
        sctx.putImageData(image, 0, 0);
        return sprite;
    }

    // Gas clouds, for the systems in a nebula
    function nebulaClouds() {
        var size = 256, sprite = makeCanvas(size), sctx = sprite.getContext('2d');
        var image = sctx.createImageData(size, size);
        for (var y = 0; y < size; y++) {
            for (var x = 0; x < size; x++) {
                var dx = (x - size / 2) / (size / 2), dy = (y - size / 2) / (size / 2), distance = Math.sqrt(dx * dx + dy * dy);
                if (distance >= 1) { continue; }
                var gas = clamp((noise(x / 30 + 3, y / 30 + 7) - 0.38) * 2.6, 0, 1) * (1 - distance);
                var rgb = mix(starColors.edge, starColors.mid, noise(x / 40, y / 40));
                var i = (y * size + x) * 4;
                image.data[i] = rgb[0];
                image.data[i + 1] = rgb[1];
                image.data[i + 2] = rgb[2];
                image.data[i + 3] = gas * 170;
            }
        }
        sctx.putImageData(image, 0, 0);
        return sprite;
    }

    var surfaceA = starSurface(0), surfaceB = starSurface(31), corona = starCorona();
    var clouds = root.dataset.star === 'nebula' ? nebulaClouds() : null;


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // WORLD : one orbit per coordinate, spaced according to the size of what is on it

    var bodies = Array.prototype.map.call(root.querySelectorAll('.sysmap-body'), function (element, index) {
        return {
            element: element,
            index: index,
            type: element.dataset.type,
            subtype: element.dataset.subtype,
            colony: element.dataset.colony,
            imageUrl: element.dataset.image,
            detail: root.querySelector('.sysmap-detail[data-index="' + index + '"]'),
            row: document.querySelector('.sysmap-row[data-index="' + index + '"]'),
            phase: index * 2.399963,  // Golden angle : bodies spread evenly around the star
            orbit: 0, speed: 0, radius: 0, x: 0, y: 0, z: 0, hitSize: 0
        };
    });

    var starRadius = STAR_RADIUS[root.dataset.star] || 1;
    var nextOrbit = starRadius * 1.5 + 1;
    bodies.forEach(function (body) {
        if (body.type === 'star') {
            body.radius = starRadius;
            return;
        }
        body.radius = BODY_RADIUS[body.type] || 0.4;
        body.orbit = nextOrbit + body.radius;
        body.speed = 0.75 / Math.pow(body.orbit, 1.5);
        nextOrbit = body.orbit + body.radius + 0.6;
    });
    var worldRadius = nextOrbit;

    // Rocks and ice : a thin ring for belts, a thick shell for Oort clouds
    var particles = [];
    var particleScale = window.innerWidth < 768 ? 0.5 : 1;
    bodies.forEach(function (body) {
        var isBelt = body.type === 'asteroid_belt', isCloud = body.type === 'oort_cloud';
        if (!isBelt && !isCloud) { return; }
        var count = (isBelt ? 520 : 620) * particleScale;
        for (var i = 0; i < count; i++) {
            var spread = isBelt ? (random() + random() - 1) * body.radius : (random() - 0.5) * 2.2 * body.radius;
            var orbit = body.orbit + spread;
            particles.push({
                body: body,
                orbit: orbit,
                angle: random() * Math.PI * 2,
                speed: 0.75 / Math.pow(orbit, 1.5),
                z: (random() - 0.5) * (isBelt ? 0.22 : 2.6),
                size: isBelt ? 0.5 + random() * random() * 2.2 : 0.4 + random() * 1,
                alpha: 0.35 + random() * 0.65,
                tone: isBelt ? 'rgb(' + (150 + random() * 60 | 0) + ',' + (135 + random() * 45 | 0) + ',' + (115 + random() * 35 | 0) + ')' : 'rgb(190,215,255)',
                x: 0, y: 0, z2: 0
            });
        }
    });

    // The illustrations load one after the other, a body without picture is drawn as a plain disc
    bodies.forEach(function (body) {
        if (body.type !== 'telluric' && body.type !== 'jovian' && body.type !== 'planetoid') { return; }
        var picture = new Image();
        picture.onload = function () {
            // Reduced copies : a 768px picture shrunk to 30px on every frame looks noisy and costs a lot
            body.small = pictureSprite(picture, 160);
            body.large = pictureSprite(picture, Math.min(picture.width, 640));
        };
        picture.src = body.imageUrl;
    });

    function pictureSprite(picture, size) {
        var sprite = makeCanvas(size), sctx = sprite.getContext('2d');
        sctx.imageSmoothingQuality = 'high';
        sctx.drawImage(picture, 0, 0, size, size);
        // The corners fade out, the background of the illustration would show as a square when zoomed in
        var mask = sctx.createRadialGradient(size / 2, size / 2, size * 0.36, size / 2, size / 2, size * 0.5);
        mask.addColorStop(0, '#000');
        mask.addColorStop(1, 'rgba(0,0,0,0)');
        sctx.globalCompositeOperation = 'destination-in';
        sctx.fillStyle = mask;
        sctx.fillRect(0, 0, size, size);
        return sprite;
    }


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // CAMERA

    var camera = {yaw: DEFAULT_YAW, tilt: DEFAULT_TILT, zoom: 1, x: 0, y: 0};
    var target = {yaw: DEFAULT_YAW, tilt: DEFAULT_TILT, zoom: 1};
    var view = {width: 0, height: 0, centerX: 0, centerY: 0, scale: 1, distance: 40};
    var followed = null;

    function resize() {
        var ratio = Math.min(window.devicePixelRatio || 1, 2);
        view.width = scene.clientWidth;
        view.height = scene.clientHeight;
        canvas.width = view.width * ratio;
        canvas.height = view.height * ratio;
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);

        // The panel lies over the scene on large screens : center on what stays visible
        var panelOverScene = getComputedStyle(panel).position === 'absolute';
        var usableWidth = view.width - (panelOverScene ? panel.offsetWidth + 24 : 0);
        view.centerX = usableWidth / 2;
        view.centerY = view.height * 0.53;

        var fitWidth = usableWidth / (2 * worldRadius * 1.05);
        var fitHeight = view.height / (2 * worldRadius * (Math.cos(DEFAULT_TILT) + 0.1) * 1.18);
        view.scale = clamp(Math.min(fitWidth, fitHeight), 8, 62);
        view.distance = worldRadius * 2.8;
        buildStarfield();
    }

    function project(x, y, z) {
        var cosYaw = Math.cos(camera.yaw), sinYaw = Math.sin(camera.yaw);
        var cosTilt = Math.cos(camera.tilt), sinTilt = Math.sin(camera.tilt);
        var worldX = x - camera.x, worldY = y - camera.y;
        var turnedX = worldX * cosYaw - worldY * sinYaw;
        var turnedY = worldX * sinYaw + worldY * cosYaw;
        var depth = turnedY * sinTilt + z * cosTilt;  // Positive : towards the viewer
        var perspective = view.distance / Math.max(view.distance - depth, 1);
        return {
            x: view.centerX + turnedX * view.scale * camera.zoom * perspective,
            y: view.centerY + (turnedY * cosTilt - z * sinTilt) * view.scale * camera.zoom * perspective,
            depth: depth,
            perspective: perspective
        };
    }


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // DRAWING

    var starfield = null;

    function buildStarfield() {
        // Twice the width : it scrolls with the camera and wraps around
        starfield = makeCanvas(view.width * 2, view.height);
        var sctx = starfield.getContext('2d');
        var deep = sctx.createRadialGradient(view.width, view.height * 0.5, 0, view.width, view.height * 0.5, view.width);
        deep.addColorStop(0, '#0c1224');
        deep.addColorStop(1, '#02040a');
        sctx.fillStyle = deep;
        sctx.fillRect(0, 0, view.width * 2, view.height);
        var starsRandom = seededRandom(424242);
        var count = view.width * view.height / 1600;
        for (var i = 0; i < count; i++) {
            var brightness = starsRandom();
            sctx.globalAlpha = 0.2 + brightness * brightness * 0.8;
            sctx.fillStyle = starsRandom() < 0.2 ? '#ffd9b0' : (starsRandom() < 0.3 ? '#b8d0ff' : '#ffffff');
            var size = brightness > 0.96 ? 1.8 : (brightness > 0.7 ? 1.1 : 0.7);
            sctx.fillRect(starsRandom() * view.width * 2, starsRandom() * view.height, size, size);
        }
        sctx.globalAlpha = 1;
    }

    function drawBackground() {
        var offset = ((camera.yaw * 90) % view.width + view.width) % view.width;
        ctx.drawImage(starfield, -offset, 0);
    }

    function drawOrbitPart(body, front) {
        // Only the half on the requested side of the star, so that it passes behind or in front of it
        var selected = body.index === selectedIndex;
        ctx.strokeStyle = selected ? accent : 'rgba(170,195,235,1)';
        ctx.lineWidth = selected ? 1.4 : 1;
        ctx.globalAlpha = selected ? 0.9 : (body.type === 'asteroid_belt' || body.type === 'oort_cloud' ? 0.1 : 0.24);
        ctx.beginPath();
        var drawing = false, steps = 96;
        for (var i = 0; i <= steps; i++) {
            var angle = i / steps * Math.PI * 2;
            var point = project(Math.cos(angle) * body.orbit, Math.sin(angle) * body.orbit, 0);
            if ((point.depth >= 0) === front) {
                if (drawing) { ctx.lineTo(point.x, point.y); } else { ctx.moveTo(point.x, point.y); drawing = true; }
            } else {
                drawing = false;
            }
        }
        ctx.stroke();
        ctx.globalAlpha = 1;
    }

    function drawParticles(front) {
        for (var i = 0; i < particles.length; i++) {
            var particle = particles[i];
            if ((particle.z2 >= 0) !== front) { continue; }
            var selected = particle.body.index === selectedIndex;
            ctx.globalAlpha = particle.alpha * (selected ? 1 : 0.7) * clamp(particle.perspective, 0.5, 1);
            ctx.fillStyle = selected ? accent : particle.tone;
            var size = particle.size * clamp(camera.zoom, 0.8, 2.5) * particle.perspective;
            ctx.fillRect(particle.x, particle.y, size, size);
        }
        ctx.globalAlpha = 1;
    }

    function drawStar(body, now) {
        var point = project(0, 0, 0);
        var radius = body.radius * view.scale * camera.zoom * point.perspective;
        var seconds = reducedMotion ? 0 : now / 1000;

        if (clouds) {
            var cloudSize = worldRadius * 2.4 * view.scale * camera.zoom;
            ctx.save();
            ctx.globalCompositeOperation = 'lighter';
            ctx.translate(point.x, point.y);
            ctx.scale(1, Math.max(Math.cos(camera.tilt) + 0.3, 0.45));
            ctx.rotate(seconds * 0.008);
            ctx.drawImage(clouds, -cloudSize / 2, -cloudSize / 2, cloudSize, cloudSize);
            ctx.restore();
        }

        // Corona, breathing slowly
        ctx.save();
        ctx.globalCompositeOperation = 'lighter';
        ctx.translate(point.x, point.y);
        ctx.rotate(seconds * 0.02);
        var coronaSize = radius * (7.5 + Math.sin(seconds * 0.7) * 0.25);
        ctx.drawImage(corona, -coronaSize / 2, -coronaSize / 2, coronaSize, coronaSize);
        ctx.rotate(seconds * -0.05);
        ctx.globalAlpha = 0.6;
        ctx.drawImage(corona, -coronaSize * 0.36, -coronaSize * 0.36, coronaSize * 0.72, coronaSize * 0.72);
        ctx.restore();

        // Two surfaces turning in opposite directions make the plasma look alive
        ctx.save();
        ctx.translate(point.x, point.y);
        ctx.rotate(seconds * 0.025);
        ctx.drawImage(surfaceA, -radius, -radius, radius * 2, radius * 2);
        ctx.rotate(seconds * -0.06);
        ctx.globalAlpha = 0.55;
        ctx.drawImage(surfaceB, -radius, -radius, radius * 2, radius * 2);
        ctx.restore();

        body.screen = {x: point.x, y: point.y, radius: radius, depth: 0};
    }

    function drawPlanet(body) {
        var point = body.point;
        var radius = Math.max(body.radius * view.scale * camera.zoom * point.perspective, 4);
        var x = point.x, y = point.y;

        // What is behind (star, orbits, rocks) must not show through the planet
        ctx.fillStyle = '#000';
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fill();

        if (body.small) {
            var pictureSize = radius * 2 / DISC_IN_PICTURE;
            ctx.save();
            ctx.imageSmoothingQuality = 'high';
            ctx.globalCompositeOperation = 'screen';  // The black around the planet of the illustration vanishes
            ctx.drawImage(pictureSize > 130 ? body.large : body.small, x - pictureSize / 2, y - pictureSize / 2, pictureSize, pictureSize);
            ctx.restore();
        } else {
            ctx.fillStyle = '#6d7f96';
            ctx.beginPath();
            ctx.arc(x, y, radius, 0, Math.PI * 2);
            ctx.fill();
        }

        // Day and night : direction of the star as seen from the planet
        var star = project(0, 0, 0);
        var toStarX = star.x - x, toStarY = star.y - y;
        var toStarZ = -point.depth * view.scale * camera.zoom;
        var length = Math.sqrt(toStarX * toStarX + toStarY * toStarY + toStarZ * toStarZ) || 1;
        var litX = x + toStarX / length * radius * 0.8, litY = y + toStarY / length * radius * 0.8;
        var facing = toStarZ / length;  // 1 : fully lit side facing us, -1 : we only see the night side
        var shade = ctx.createRadialGradient(litX, litY, radius * 0.1, litX, litY, radius * (1.55 + facing * 0.65));
        shade.addColorStop(0, 'rgba(0,0,6,0)');
        shade.addColorStop(0.6, 'rgba(0,0,6,0.15)');
        shade.addColorStop(1, 'rgba(0,0,6,0.94)');
        ctx.fillStyle = shade;
        ctx.beginPath();
        ctx.arc(x, y, radius + 0.5, 0, Math.PI * 2);
        ctx.fill();

        body.screen = {x: x, y: y, radius: radius, depth: point.depth};
    }

    function drawBandMarker(body) {
        // Belts and clouds have no single position : a small beacon gives them a place to click on
        var point = body.point;
        var size = 4 * clamp(point.perspective * camera.zoom, 1, 1.8);
        ctx.fillStyle = body.type === 'oort_cloud' ? '#bcd7ff' : '#d8c6a4';
        ctx.save();
        ctx.translate(point.x, point.y);
        ctx.rotate(Math.PI / 4);
        ctx.fillRect(-size / 2, -size / 2, size, size);
        ctx.restore();
        body.screen = {x: point.x, y: point.y, radius: size, depth: point.depth};
    }

    function drawBody(body, now) {
        if (body.type === 'star') { drawStar(body, now); }
        else if (body.type === 'asteroid_belt' || body.type === 'oort_cloud') { drawBandMarker(body); }
        else { drawPlanet(body); }
    }

    function drawMarks(body, now) {
        var mark = body.screen;
        if (body.colony) {
            ctx.strokeStyle = body.colony === 'mine' ? mineColor : otherColor;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.arc(mark.x, mark.y, mark.radius + 4, 0, Math.PI * 2);
            ctx.stroke();
        }
        if (body.index === selectedIndex) {
            // Targeting brackets
            var gap = mark.radius + (body.colony ? 9 : 7);
            var turn = reducedMotion ? 0 : now / 2500;
            ctx.strokeStyle = accent;
            ctx.lineWidth = 2;
            for (var i = 0; i < 4; i++) {
                var start = turn + i * Math.PI / 2;
                ctx.beginPath();
                ctx.arc(mark.x, mark.y, gap, start, start + Math.PI / 4);
                ctx.stroke();
            }
        }
    }

    function placeButton(body) {
        var mark = body.screen;
        var size = Math.max(40, mark.radius * 2 + 6);
        if (Math.abs(size - body.hitSize) > 2) {
            body.hitSize = size;
            body.element.style.width = size + 'px';
            body.element.style.height = size + 'px';
        }
        body.element.style.transform = 'translate(' + (mark.x - body.hitSize / 2) + 'px,' + (mark.y - body.hitSize / 2) + 'px)';
        body.element.style.zIndex = Math.round(100 + mark.depth);
    }


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // MAIN LOOP

    var clock = 0, speedFactor = 1, paused = reducedMotion, hovered = false;
    var lastFrame = null, frameRequest = null, sceneVisible = true;

    function update(deltaSeconds) {
        // Slows down under the mouse, to catch a moving body without effort
        var wantedSpeed = paused || hovered ? 0 : 1;
        speedFactor += (wantedSpeed - speedFactor) * Math.min(deltaSeconds * 4, 1);
        clock += deltaSeconds * speedFactor;

        var ease = Math.min(deltaSeconds * 5, 1);
        camera.yaw += (target.yaw - camera.yaw) * ease;
        camera.tilt += (target.tilt - camera.tilt) * ease;
        camera.zoom += (target.zoom - camera.zoom) * ease;

        bodies.forEach(function (body) {
            var angle = body.phase + clock * body.speed;
            body.x = Math.cos(angle) * body.orbit;
            body.y = Math.sin(angle) * body.orbit;
        });

        var goalX = followed ? followed.x : 0, goalY = followed ? followed.y : 0;
        camera.x += (goalX - camera.x) * ease;
        camera.y += (goalY - camera.y) * ease;

        bodies.forEach(function (body) { body.point = project(body.x, body.y, 0); });
        particles.forEach(function (particle) {
            var angle = particle.angle + clock * particle.speed;
            var point = project(Math.cos(angle) * particle.orbit, Math.sin(angle) * particle.orbit, particle.z);
            particle.x = point.x;
            particle.y = point.y;
            particle.z2 = point.depth;
            particle.perspective = point.perspective;
        });
    }

    function draw(now) {
        drawBackground();

        var sorted = bodies.slice().sort(function (a, b) { return a.point.depth - b.point.depth; });
        var star = bodies[0];

        bodies.forEach(function (body) { if (body.orbit) { drawOrbitPart(body, false); } });
        drawParticles(false);
        sorted.forEach(function (body) { if (body !== star && body.point.depth < 0) { drawBody(body, now); } });
        drawBody(star, now);
        bodies.forEach(function (body) { if (body.orbit) { drawOrbitPart(body, true); } });
        drawParticles(true);
        sorted.forEach(function (body) { if (body !== star && body.point.depth >= 0) { drawBody(body, now); } });

        bodies.forEach(function (body) {
            drawMarks(body, now);
            placeButton(body);
        });
    }

    function frame(now) {
        frameRequest = null;
        var deltaSeconds = lastFrame === null ? 0 : Math.min((now - lastFrame) / 1000, 0.1);
        lastFrame = now;
        update(deltaSeconds);
        draw(now);
        requestFrame();
    }

    function requestFrame() {
        if (sceneVisible && !document.hidden && frameRequest === null) {
            frameRequest = requestAnimationFrame(frame);
        }
    }

    // Nothing is computed while the scene can't be seen
    document.addEventListener('visibilitychange', function () { lastFrame = null; requestFrame(); });
    new IntersectionObserver(function (entries) {
        sceneVisible = entries[0].isIntersecting;
        lastFrame = null;
        requestFrame();
    }).observe(scene);
    new ResizeObserver(resize).observe(scene);


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // SELECTION

    var selectedIndex = -1;

    function select(index) {
        selectedIndex = index;
        bodies.forEach(function (body) {
            var isSelected = body.index === index;
            body.element.classList.toggle('is-selected', isSelected);
            body.element.setAttribute('aria-pressed', isSelected);
            body.detail.hidden = !isSelected;
            if (body.row) { body.row.classList.toggle('is-selected', isSelected); }
        });
        panel.scrollTop = 0;
        if (followed) { follow(bodies[index]); }
        history.replaceState(null, '', '#orbit-' + index);
    }

    function follow(body) {
        followed = body;
        if (body) { target.zoom = Math.max(target.zoom, body.type === 'star' ? 2 : 3.2); }
        root.querySelectorAll('[data-action="follow"]').forEach(function (button) {
            button.setAttribute('aria-pressed', body ? 'true' : 'false');
        });
    }

    function resetView() {
        followed = null;
        follow(null);
        target.yaw = DEFAULT_YAW;
        target.tilt = DEFAULT_TILT;
        target.zoom = 1;
    }

    function initialSelection() {
        var fromUrl = /^#orbit-(\d+)$/.exec(window.location.hash);
        if (fromUrl && bodies[fromUrl[1]]) { return Number(fromUrl[1]); }
        var myColony = bodies.filter(function (body) { return body.colony === 'mine'; })[0];
        return myColony ? myColony.index : 0;
    }


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // INTERACTIONS

    var drag = null, draggedSinceDown = false;

    scene.addEventListener('pointerdown', function (event) {
        if (event.target.closest('.sysmap-controls')) { return; }
        drag = {x: event.clientX, y: event.clientY, id: event.pointerId};
        draggedSinceDown = false;
    });
    window.addEventListener('pointermove', function (event) {
        if (!drag || event.pointerId !== drag.id) { return; }
        var moveX = event.clientX - drag.x, moveY = event.clientY - drag.y;
        if (!draggedSinceDown && Math.abs(moveX) + Math.abs(moveY) < 5) { return; }
        draggedSinceDown = true;
        scene.classList.add('is-dragging');
        target.yaw += moveX * 0.006;
        if (event.pointerType === 'mouse') {  // On a touch screen, moving vertically scrolls the page
            target.tilt = clamp(target.tilt - moveY * 0.005, 0.25, 1.42);
        }
        drag.x = event.clientX;
        drag.y = event.clientY;
    });
    function endDrag() {
        drag = null;
        scene.classList.remove('is-dragging');
    }
    window.addEventListener('pointerup', endDrag);
    window.addEventListener('pointercancel', endDrag);

    scene.addEventListener('wheel', function (event) {
        var zoomed = clamp(target.zoom * Math.exp(-event.deltaY * 0.0012), MIN_ZOOM, MAX_ZOOM);
        // At the limits the page scrolls again, the mouse must not stay trapped in the scene
        if (zoomed !== target.zoom) {
            event.preventDefault();
            target.zoom = zoomed;
        }
    }, {passive: false});

    bodies.forEach(function (body) {
        body.element.addEventListener('click', function () {
            if (!draggedSinceDown) { select(body.index); }
        });
        body.element.addEventListener('dblclick', function () {
            select(body.index);
            follow(body);
        });
        body.element.addEventListener('pointerenter', function (event) {
            if (event.pointerType === 'mouse') { hovered = true; }
        });
        body.element.addEventListener('pointerleave', function () { hovered = false; });

        if (body.row) {
            body.row.addEventListener('click', function (event) {
                if (event.target.closest('a')) { return; }
                select(body.index);
                scene.scrollIntoView({block: 'nearest', behavior: reducedMotion ? 'auto' : 'smooth'});
            });
        }
    });

    root.addEventListener('keydown', function (event) {
        if (event.target.tagName === 'INPUT') { return; }
        if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
            event.preventDefault();
            var step = event.key === 'ArrowRight' ? 1 : -1;
            var index = (selectedIndex + step + bodies.length) % bodies.length;
            select(index);
            bodies[index].element.focus();
        }
    });

    root.addEventListener('click', function (event) {
        var button = event.target.closest('[data-action]');
        if (!button) { return; }
        var action = button.dataset.action;
        if (action === 'pause') {
            paused = !paused;
            updatePauseButton();
        } else if (action === 'zoom-in') {
            target.zoom = clamp(target.zoom * 1.35, MIN_ZOOM, MAX_ZOOM);
        } else if (action === 'zoom-out') {
            target.zoom = clamp(target.zoom / 1.35, MIN_ZOOM, MAX_ZOOM);
        } else if (action === 'reset') {
            resetView();
        } else if (action === 'follow') {
            if (followed === bodies[selectedIndex]) { resetView(); } else { follow(bodies[selectedIndex]); }
        }
    });

    function updatePauseButton() {
        var button = root.querySelector('[data-action="pause"]');
        button.setAttribute('aria-pressed', paused);
        button.querySelector('i').className = paused ? 'fas fa-play' : 'fas fa-pause';
    }


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

    updatePauseButton();
    select(initialSelection());
    resize();
    requestFrame();

})();
