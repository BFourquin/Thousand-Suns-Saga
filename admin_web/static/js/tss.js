// Behaviours declared in the templates with data attributes, so that the pages need no inline script.

$(function () {

    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // GENERIC ATTRIBUTES

    $(document).on('change', '[data-autosubmit]', function () { this.form.submit(); });
    $(document).on('click', '[data-confirm]', function () { return confirm($(this).data('confirm')); });
    $(document).on('click', '[data-href]', function (e) {
        // A link inside a clickable row keeps its own destination
        if (!$(e.target).closest('a, button, input, label').length) { window.location.href = $(this).data('href'); }
    });

    // Filters take the whole screen of a phone : they start folded. <div class="card" data-collapse-on-mobile>
    if (window.innerWidth < 992) {
        $('[data-collapse-on-mobile]').addClass('collapsed-card').find('[data-card-widget="collapse"] i').toggleClass('fa-minus fa-plus');
    }

    // <input data-must-match="name of the other field" data-mismatch-message="...">
    $(document).on('input', 'form input', function () {
        $(this.form).find('[data-must-match]').each(function () {
            var same = this.value === this.form.elements[this.dataset.mustMatch].value;
            this.setCustomValidity(same ? '' : this.dataset.mismatchMessage);
        });
    });


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // VIEW COUNTER : <form data-view-after="seconds" action="url"> sent once the page stayed that long with its tab active

    $('form[data-view-after]').each(function () {
        var form = $(this), seconds = 0;
        var timer = setInterval(function () {
            if (document.hidden) { return; }
            seconds += 1;
            if (seconds >= form.data('view-after')) {
                clearInterval(timer);
                $.post(form.attr('action'), form.serialize());
            }
        }, 1000);
    });


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // TEXT TOOLBAR : includes/text_toolbar.html, just before the textarea it formats

    function toolbar_textarea(control) { return $(control).closest('[data-text-toolbar]').nextAll('textarea')[0]; }

    function selected_text(area) { return area.value.slice(area.selectionStart, area.selectionEnd); }

    function replace_selection(area, before, text, after) {
        var start = area.selectionStart + before.length;
        area.setRangeText(before + text + after, area.selectionStart, area.selectionEnd);
        area.setSelectionRange(start, start + text.length);
        area.focus();
    }

    $(document).on('click', '[data-text-toolbar] button[data-tag]', function () {
        var area = toolbar_textarea(this);
        replace_selection(area, '[' + this.dataset.tag + ']', selected_text(area), '[/' + this.dataset.tag + ']');
    });

    $(document).on('change', '[data-text-toolbar] select[data-tag]', function () {
        var area = toolbar_textarea(this);
        replace_selection(area, '[' + this.dataset.tag + '=' + this.value + ']', selected_text(area), '[/' + this.dataset.tag + ']');
        this.selectedIndex = 0;  // So that the same choice can be made again
    });

    $(document).on('click', '[data-text-toolbar] button[data-link]', function () {
        var area = toolbar_textarea(this), url = window.prompt(this.dataset.prompt, 'https://');
        if (!url) { return; }
        var text = selected_text(area);
        replace_selection(area, text ? '[url=' + url + ']' : '[url]', text || url, '[/url]');
    });

    $(document).on('click', '[data-text-toolbar] button[data-remove-format]', function () {
        var area = toolbar_textarea(this);
        replace_selection(area, '', selected_text(area).replace(/\[\/?(?:b|i|u|s|left|center|right|justify|size|color|url)(?:=[^\[\]\n]*)?\]/gi, ''), '');
    });


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // FORMS SENT TO THE JSON API : <form data-api-url="api_name">

    // Toasts built in AdminLTE : https://adminlte.io/docs/3.0/javascript/toasts.html
    var popup_class_level = {'success': 'bg-success', 'info': 'bg-info', 'warning': 'bg-warning', 'danger': 'bg-danger'};

    function popup(json) {
        var toast = {};
        if (popup_class_level.hasOwnProperty(json.level)) { toast['class'] = popup_class_level[json.level]; }
        if (json.hasOwnProperty("title")) { toast['title'] = json.title; }
        if (json.hasOwnProperty("subtitle")) { toast['subtitle'] = json.subtitle; }
        if (json.hasOwnProperty("body")) { toast['body'] = json.body; }
        toast['autohide'] = json.hasOwnProperty("autohide") ? json.autohide : true;
        toast['delay'] = json.hasOwnProperty("delay") ? json.delay : 3000;
        $(document).Toasts('create', toast);
    }

    function api_interaction(json) {
        // Anything but JSON (server error, CSRF refusal, network failure...) : the player still has to be told
        if (!json || typeof json !== 'object') {
            console.error("JSON response invalid or empty");
            json = {"popup": true, "level": "danger", "title": document.documentElement.dataset.errorMessage};
        }
        if (json.hasOwnProperty("popup")) { popup(json); }
        if (json.hasOwnProperty("redirect")) { window.location.href = json.redirect; }
    }

    $(document).on('submit', 'form[data-api-url]', function (e) {
        e.preventDefault();
        $.ajax({
            url: '/' + $(this).data('api-url') + '/',
            data: $(this).serialize(),
            type: 'POST',
            success: function (data) { api_interaction(data); },
            error: function (data) { api_interaction(data.responseJSON); }
        });
    });


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // TABLES : <table data-datatable data-hidden-columns="0,1,3">

    $('table[data-datatable]').each(function () {
        var hidden_columns = $(this).data('hidden-columns');
        var table = $(this).DataTable({
            "responsive": true,
            "lengthChange": true,
            "pageLength": 50,
            "autoWidth": false,
            "buttons": ["copy", "csv", "excel", "pdf", "print", "colvis"],
            "columnDefs": [{ targets: hidden_columns === undefined ? [] : String(hidden_columns).split(',').map(Number), visible: false }],
        });
        table.buttons().container().appendTo($(table.table().container()).find('.col-md-6:eq(0)'));
    });


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // RANGE SLIDERS

    // Only where there is one : the admin pages load jQuery again, without the plugin
    if ($('.js-range-slider').length) {
        $('.js-range-slider').ionRangeSlider({ min: 0, max: 100, from: 100, type: 'single', step: 1, postfix: '%' });
    }


    ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////
    // REPORTS

    //Enable check and uncheck all functionality
    $('.checkbox-toggle').click(function () {
        var clicks = $(this).data('clicks');
        if (clicks) {
            //Uncheck all checkboxes
            $('.mailbox-messages input[type=\'checkbox\']').prop('checked', false);
            $('.checkbox-toggle .far.fa-check-square').removeClass('fa-check-square').addClass('fa-square');
        } else {
            //Check all checkboxes
            $('.mailbox-messages input[type=\'checkbox\']').prop('checked', true);
            $('.checkbox-toggle .far.fa-square').removeClass('fa-square').addClass('fa-check-square');
        }
        $(this).data('clicks', !clicks);
    });

    //Handle starring for font awesome
    $('.mailbox-star').click(function (e) {
        e.preventDefault();
        var $this = $(this).find('a > i');
        if ($this.hasClass('fa')) {
            $this.toggleClass('fa-star');
            $this.toggleClass('fa-star-o');
        }
    });

    // Keep current page parameters when following a filter link
    $("a[rel~='keep-params']").click(function (e) {
        e.preventDefault();

        var currentParams = new URLSearchParams(window.location.search);
        var url = new URL($(this).attr('href'), window.location.origin);

        // Merge parameters, avoiding duplicates
        new URLSearchParams(url.search).forEach(function (value, key) {
            currentParams.set(key, value);
        });

        var dest = url.origin + url.pathname + '?' + currentParams.toString();

        // Short timeout to overcome browser bugs
        window.setTimeout(function () { window.location.href = dest; }, 100);
    });

});
