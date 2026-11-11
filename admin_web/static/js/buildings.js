// Tree of the buildings (page /buildings/) : draws the upgrade links, hides the obsolete and the future levels.
// The nodes are placed in the grid by the template.

(function () {
    'use strict';

    var tree = document.getElementById('btree');
    if (!tree) { return; }
    var grid = document.getElementById('btree-grid');
    var links = document.getElementById('btree-links');
    var nodes = tree.querySelectorAll('.btree-node');
    var SVG_NS = 'http://www.w3.org/2000/svg';

    function drawLink(parent, child) {
        // A hidden node has no offsetParent
        if (!parent || !parent.offsetParent || !child.offsetParent) { return; }
        var origin = grid.getBoundingClientRect();
        var from = parent.getBoundingClientRect();
        var to = child.getBoundingClientRect();
        var x1 = from.right - origin.left, y1 = from.top + from.height / 2 - origin.top;
        var x2 = to.left - origin.left, y2 = to.top + to.height / 2 - origin.top;
        var middle = (x1 + x2) / 2;

        var path = document.createElementNS(SVG_NS, 'path');
        path.setAttribute('d', 'M' + x1 + ' ' + y1 + ' C' + middle + ' ' + y1 + ' ' + middle + ' ' + y2 + ' ' + x2 + ' ' + y2);
        if (child.classList.contains('btree-current')) { path.classList.add('btree-link-current'); }
        links.appendChild(path);
    }

    function drawLinks() {
        links.replaceChildren();
        links.setAttribute('width', grid.scrollWidth);
        links.setAttribute('height', grid.scrollHeight);
        nodes.forEach(function (node) {
            node.dataset.parents.split(',').filter(Boolean).forEach(function (name) {
                drawLink(document.getElementById('btree-node-' + name), node);
            });
        });
    }

    ['btree-hide-past', 'btree-hide-future'].forEach(function (option) {
        var checkbox = document.getElementById(option);

        // The choice follows the player from one category to another. Without storage, the defaults of the page stay.
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
