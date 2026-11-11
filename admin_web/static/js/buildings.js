// Trees of buildings of the colony page (includes/colony/building_tree.html) : the links drawn once a tree is visible,
// the chosen building described under its tree, the actions of a building card opening their part of its modal.

(function () {
    'use strict';

    var SVG_NS = 'http://www.w3.org/2000/svg';

    function draw(tree) {
        var grid = tree.querySelector('.btree-grid');
        var links = tree.querySelector('.btree-links');
        links.replaceChildren();
        if (!grid.offsetParent) { return; }  // Hidden in a modal, a tab or a collapse : drawn when shown
        links.setAttribute('width', grid.scrollWidth);
        links.setAttribute('height', grid.scrollHeight);

        var origin = grid.getBoundingClientRect();
        grid.querySelectorAll('[data-parents]').forEach(function (node) {
            node.dataset.parents.split(',').filter(Boolean).forEach(function (name) {
                var parent = grid.querySelector('[data-name="' + CSS.escape(name) + '"]');
                if (!parent) { return; }
                // From the top of the lower level to the bottom of the upgrade
                var from = parent.getBoundingClientRect(), to = node.getBoundingClientRect();
                var x1 = from.left + from.width / 2 - origin.left, y1 = from.top - origin.top;
                var x2 = to.left + to.width / 2 - origin.left, y2 = to.bottom - origin.top;
                var middle = (y1 + y2) / 2;
                var path = document.createElementNS(SVG_NS, 'path');
                path.setAttribute('d', 'M' + x1 + ' ' + y1 + ' C' + x1 + ' ' + middle + ' ' + x2 + ' ' + middle + ' ' + x2 + ' ' + y2);
                links.appendChild(path);
            });
        });
    }

    function drawVisible() {
        document.querySelectorAll('[data-btree]').forEach(draw);
    }

    $(document).on('shown.bs.modal shown.bs.tab shown.bs.collapse', drawVisible);
    window.addEventListener('resize', drawVisible);

    $(document).on('change', '[data-btree] input', function () {
        $(this).closest('form').find('[data-btree-choice]').text($(this).closest('label').attr('title'));
    });

    // <a data-toggle="modal" data-section="#id of a collapse"> : the modal opens on that part
    $(document).on('show.bs.modal', '.modal', function (e) {
        var section = e.relatedTarget && $(e.relatedTarget).data('section');
        $(this).find('.collapse.show').not(section).collapse('hide');
        if (section) { $(section).collapse('show'); }
    });
})();
