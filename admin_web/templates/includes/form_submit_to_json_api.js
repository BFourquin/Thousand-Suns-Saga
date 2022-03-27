

<script>

    $(document).ready(function() {
        $('#{{form}}').submit(function(e) {
            e.preventDefault();
            $.ajax({
                url: '/{{form}}/',
            data: $(this).serialize(),
            type: 'POST',
            success: function(data) {alert(data.responseJSON.message)},
            error: function(data) {alert('[Erreur ' + data.status + '] ' + data.responseJSON.message)}
            });
        });
    });

</script>