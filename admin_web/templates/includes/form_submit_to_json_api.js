

<script>

    function popup(json) {

      if (json.hasOwnProperty("redirect")) {
        window.location.href = 'newPage.html';
      }

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
                success: function(data) {popup(data.responseJSON)},
                // error: function(data) {alert('[Erreur ' + data.status + '] ' + data.responseJSON.message)}
                error: function(data) {popup(data.responseJSON)}
            });
        });
    });


</script>