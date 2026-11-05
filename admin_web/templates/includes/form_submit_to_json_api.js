

<script>

    // Toasts built in AdminLTE : https://adminlte.io/docs/3.0/javascript/toasts.html
    var popup_class_level = {'success': 'bg-success', 'info': 'bg-info', 'warning': 'bg-warning', 'danger': 'bg-danger'};

    function api_interaction(json) {
      // Anything but JSON (server error, CSRF refusal, network failure...) : the player still has to be told
      if (!json || typeof json !== 'object') {
        console.error("JSON response invalid or empty");
        json = {"popup": true, "level": "danger", "title": "Une erreur est survenue, veuillez réessayer"};
      }
      if (json.hasOwnProperty("popup")) { popup(json); }
      if (json.hasOwnProperty("redirect")) { redirect(json); }
    }

    function redirect(json) {

      if (json.hasOwnProperty("redirect")) {
        window.location.href = json.redirect;
      }
    };

    function popup(json) {

      var toast = {}
      if (popup_class_level.hasOwnProperty(json.level)) {toast['class'] = popup_class_level[json.level];}
      if (json.hasOwnProperty("title")) {toast['title'] = json.title;}
      if (json.hasOwnProperty("subtitle")) {toast['subtitle'] = json.subtitle;}
      if (json.hasOwnProperty("body")) {toast['body'] = json.body;}
      if (json.hasOwnProperty("autohide")) {toast['autohide'] = json.autohide;} else {toast['autohide'] = true;}
      if (json.hasOwnProperty("delay")) {toast['delay'] = json.delay;} else {toast['delay'] = 3000;}
      $(document).Toasts('create', toast)
    };

    //console.log("FORM ID = {{ form }}");

    $(document).ready(function() {

        $('#{{form}}').submit(function(e) {
            e.preventDefault();
            $.ajax({
                url: {% if api_url %}'/{{api_url}}/'{% else %}'/{{form}}/'{% endif %},
                data: $(this).serialize(),
                type: 'POST',
                success: function(data) {api_interaction(data)},
                error: function(data) {api_interaction(data.responseJSON)}
            })
        });
    });


</script>