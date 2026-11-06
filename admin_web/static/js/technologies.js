// Tree of the technologies (page /technologies/) : places the nodes, draws the links, hides the eras.
// The nodes open their modal by Bootstrap and start a research by the data-api-url forms of tss.js.

(function () {
    'use strict';

    var tree = document.getElementById('tech-tree');
    var inner = document.getElementById('tech-tree-inner');
    var links = document.getElementById('tech-links');
    var SVG_NS = 'http://www.w3.org/2000/svg';

    tree.style.setProperty('--tech-columns', tree.dataset.columns);

    var nodes = tree.querySelectorAll('[data-column]');
    nodes.forEach(function (node) {
        node.style.gridColumn = node.dataset.column + ' / span 2';
        node.style.gridRow = node.dataset.row;
    });

    function drawLink(parent, child) {
        // Both are in display none when their era is hidden
        if (!parent || !parent.offsetParent || !child.offsetParent) { return; }
        var origin = inner.getBoundingClientRect();
        var from = parent.getBoundingClientRect();
        var to = child.getBoundingClientRect();
        var x1 = from.left + from.width / 2 - origin.left, y1 = from.top - origin.top;
        var x2 = to.left + to.width / 2 - origin.left, y2 = to.bottom - origin.top;
        var middle = (y1 + y2) / 2;

        var path = document.createElementNS(SVG_NS, 'path');
        path.setAttribute('d', 'M' + x1 + ' ' + y1 + ' C' + x1 + ' ' + middle + ' ' + x2 + ' ' + middle + ' ' + x2 + ' ' + y2);
        if (parent.classList.contains('tech-researched')) { path.classList.add('tech-link-researched'); }
        if (parent.classList.contains('tech-ghost')) { path.classList.add('tech-link-foreign'); }
        links.appendChild(path);
    }

    function drawLinks() {
        links.replaceChildren();
        links.setAttribute('width', inner.scrollWidth);
        links.setAttribute('height', inner.scrollHeight);
        nodes.forEach(function (node) {
            (node.dataset.parents || '').split(',').filter(Boolean).forEach(function (name) {
                drawLink(document.getElementById('tech-node-' + name), node);
            });
        });
    }

    ['tech-hide-future', 'tech-hide-past'].forEach(function (option) {
        var checkbox = document.getElementById(option);

        // The choice follows the player from one category to another. Without storage, the options stay checked.
        try {
            var saved = localStorage.getItem(option);
            if (saved !== null) { checkbox.checked = saved === 'true'; }
        } catch (e) {}
        tree.classList.toggle(option, checkbox.checked);

        checkbox.addEventListener('change', function () {
            tree.classList.toggle(option, checkbox.checked);
            try { localStorage.setItem(option, checkbox.checked); } catch (e) {}
            drawLinks();
        });
    });

    window.addEventListener('resize', drawLinks);
    document.fonts.ready.then(drawLinks);
    drawLinks();
})();
