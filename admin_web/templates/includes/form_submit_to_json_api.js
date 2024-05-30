

<script>

    function api_interaction(json) {
      if (json.hasOwnProperty("popup")) {popup(json)}
      if (json.hasOwnProperty("redirect")) {redirect(json)}
    };

    function redirect(json) {

      if (json.hasOwnProperty("redirect")) {
        window.location.href = json.redirect;
      }
    };

    function popup(json) {

      var toast = {}
      if (json.hasOwnProperty("class")) {toast['class'] = json.class;}
      if (json.hasOwnProperty("title")) {toast['title'] = json.title;}
      if (json.hasOwnProperty("subtitle")) {toast['subtitle'] = json.subtitle;}
      if (json.hasOwnProperty("body")) {toast['body'] = json.body;}
      if (json.hasOwnProperty("autohide")) {toast['autohide'] = json.autohide;} else {toast['autohide'] = true;}
      if (json.hasOwnProperty("delay")) {toast['delay'] = json.delay;} else {toast['delay'] = 3000;}
      $(document).Toasts('create', toast)
    };


    $(document).ready(function() {

        $('#{{form}}').submit(function(e) {
            e.preventDefault();
            $.ajax({
                url: '/{{form}}/',
                data: $(this).serialize(),
                type: 'POST',
                done: function(data) {api_interaction(data.responseJSON)},
                // error: function(data) {alert('[Erreur ' + data.status + '] ' + data.responseJSON.message)}
                error: function(data) {api_interaction(data.responseJSON)}
            })
        });
    });


</script>