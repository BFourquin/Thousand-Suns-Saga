
//!\\ Code généré par ChatGPT //!\\

document.addEventListener("DOMContentLoaded", function() {
    // Extensions Day.js
    dayjs.extend(dayjs_plugin_relativeTime);
    dayjs.extend(dayjs_plugin_utc);

    // Détecte la langue de l'utilisateur (fallback fr)
    const userLang = document.querySelector('.timeago')?.dataset.lang || navigator.language.split('-')[0] || 'fr';
    dayjs.locale(userLang);

    // Règles adaptatives hybrides
    const rules = [
        { threshold: 60, unit: "second", format: d => `${d} seconde${d>1?'s':''}` },
        { threshold: 120, unit: "second", format: (d, t, n) => {
            const min = n.diff(t, "minute")
            const sec = n.diff(t, "second") % 60
            return `${min} minute${min>1?'s':''}${sec>0 ? ' ' + sec + ' seconde' + (sec>1?'s':'') : ''}`
        }},
        { threshold: 3600, unit: "minute", format: d => `${d} minute${d>1?'s':''}` },
        { threshold: 7200, unit: "minute", format: (d, t, n) => {
            const h = n.diff(t, "hour")
            const m = n.diff(t, "minute") % 60
            return `${h}h${m>0 ? m : ''}`
        }},
        { threshold: 86400, unit: "hour", format: d => `${d} heure${d>1?'s':''}` },
        { threshold: Infinity, unit: "day", format: (d, t) => t.format("DD/MM/YYYY HH:mm") }
    ];

    function formatAdaptive(ts) {
        const now = dayjs();
        const diffSec = now.diff(ts, "second");

        for (let rule of rules) {
            if (diffSec < rule.threshold) {
                const value = now.diff(ts, rule.unit);
                return rule.format(value, ts, now);
            }
        }
    }

    function updateTimeago() {
        const now = dayjs();
        const elements = document.querySelectorAll('.timeago');

        elements.forEach(el => {
            // UTC → fuseau local
            const ts = dayjs.utc(el.dataset.timestamp).local();
            el.innerText = formatAdaptive(ts);
            el.title = ts.format("DD/MM/YYYY HH:mm");
        });

        // Intervalle adaptatif
        let minInterval = Infinity;
        elements.forEach(el => {
            const ts = dayjs.utc(el.dataset.timestamp).local();
            const age = now.diff(ts, 'second');
            if (age < 120) minInterval = Math.min(minInterval, 1000);
            else if (age < 3600) minInterval = Math.min(minInterval, 10000);
            else if (age < 86400) minInterval = Math.min(minInterval, 60000);
            else minInterval = Math.min(minInterval, 300000);
        });

        if (elements.length > 0) {
            clearTimeout(window.timeagoTimer);
            window.timeagoTimer = setTimeout(updateTimeago, minInterval);
        }
    }

    updateTimeago();
});