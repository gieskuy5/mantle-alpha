/**
 * Mantle Alpha Dashboard — Client-side JavaScript
 *
 * Auto-refreshes data from the API and updates the DOM.
 */

const REFRESH_INTERVAL = 15_000; // 15 seconds

async function fetchJSON(url) {
    try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (err) {
        console.error(`Failed to fetch ${url}:`, err);
        return null;
    }
}

async function refreshData() {
    // Fetch latest data from API
    const [eventsData, signalsData, anomaliesData] = await Promise.all([
        fetchJSON('/api/whale-events?limit=20'),
        fetchJSON('/api/signals?limit=10'),
        fetchJSON('/api/anomalies?limit=5'),
    ]);

    // Log for debugging
    if (eventsData) console.log('Whale events:', eventsData.events.length);
    if (signalsData) console.log('Signals:', signalsData.signals.length);
    if (anomaliesData) console.log('Anomaly reports:', anomaliesData.reports.length);
}

// Auto-refresh on load
document.addEventListener('DOMContentLoaded', () => {
    console.log('🧠 Mantle Alpha Dashboard loaded');
    refreshData();
    setInterval(refreshData, REFRESH_INTERVAL);
});
