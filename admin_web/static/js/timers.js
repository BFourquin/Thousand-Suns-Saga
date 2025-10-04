
//!\\ Code généré par ChatGPT //!\\

document.addEventListener("DOMContentLoaded", function() {
    dayjs.extend(dayjs_plugin_relativeTime);
    dayjs.extend(dayjs_plugin_utc);

    const userLang = document.querySelector('.timeago')?.dataset.lang || navigator.language.split('-')[0] || 'fr';
    dayjs.locale(userLang);

    function formatAdaptive(ts) {
        const now = dayjs();
        const diffSec = now.diff(ts, 'second');

        if (diffSec < 60) {
            return `${diffSec} seconde${diffSec>1?'s':''}`;
        } else if (diffSec < 3600) {
            const min = Math.floor(diffSec / 60);
            const sec = diffSec % 60;
            return `${min} minute${min>1?'s':''}${sec>0 ? ' ' + sec + ' seconde' + (sec>1?'s':'') : ''}`;
        } else if (diffSec < 86400) {
            const h = Math.floor(diffSec / 3600);
            const m = Math.floor((diffSec % 3600)/60);
            return `${h}h${m>0 ? m + 'm' : ''}`;
        } else {
            return ts.format("DD/MM/YYYY HH:mm");
        }
    }

    function updateTimeago() {
        const now = dayjs();
        const elements = document.querySelectorAll('.timeago');

        let nextInterval = 60000; // par défaut 1 min

        elements.forEach(el => {
            const ts = dayjs.utc(el.dataset.timestamp).local();
            el.innerText = formatAdaptive(ts);
            el.title = ts.format("DD/MM/YYYY HH:mm");

            const age = now.diff(ts, 'second');
            if (age < 120) nextInterval = Math.min(nextInterval, 1000);       // <2min → maj chaque sec
            else if (age < 3600) nextInterval = Math.min(nextInterval, 10000); // <1h → maj toutes les 10s
            else if (age < 86400) nextInterval = Math.min(nextInterval, 60000); // <1j → maj chaque minute
            else nextInterval = Math.min(nextInterval, 300000);                // >1j → maj toutes les 5 min
        });

        clearTimeout(window.timeagoTimer);
        window.timeagoTimer = setTimeout(updateTimeago, nextInterval);
    }

    updateTimeago(); // première mise à jour immédiate
});
