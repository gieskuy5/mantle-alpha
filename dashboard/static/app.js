/**
 * MantleAlpha Dashboard — Client-side JavaScript
 * Auto-refreshes data from API endpoints every 5 seconds.
 */

const REFRESH_INTERVAL = 5000;
let lastRefreshTime = null;

// ── Helpers ────────────────────────────────────────────────

async function fetchJSON(url) {
    try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (err) {
        console.error(`Fetch failed: ${url}`, err);
        return null;
    }
}

function formatNumber(n, decimals = 2) {
    if (n == null || isNaN(n)) return '—';
    if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return Number(n).toFixed(decimals);
}

function formatUSD(n) {
    if (n == null || isNaN(n)) return '—';
    return '$' + formatNumber(n);
}

function timeAgo(timestamp) {
    if (!timestamp) return '—';
    const now = Date.now() / 1000;
    const diff = now - timestamp;
    if (diff < 5) return 'just now';
    if (diff < 60) return Math.floor(diff) + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

function truncateAddr(addr, chars = 6) {
    if (!addr) return '—';
    return addr.slice(0, chars + 2) + '…' + addr.slice(-4);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ── Whale Events ───────────────────────────────────────────

function renderWhaleEvents(events) {
    const container = document.getElementById('whaleEventsList');
    const counter = document.getElementById('whaleCount');
    if (!events || events.length === 0) {
        container.innerHTML = '<div class="empty-state"><i class="fas fa-water"></i>No whale events detected yet</div>';
        counter.textContent = '0 events';
        return;
    }
    counter.textContent = events.length + ' events';
    container.innerHTML = events.slice(0, 15).map(ev => `
        <div class="whale-card">
            <div class="whale-card-icon">
                <i class="fas fa-${getEventTypeIcon(ev.event_type)}"></i>
            </div>
            <div class="whale-card-info">
                <div class="whale-card-header">
                    <span class="whale-card-type">${escapeHtml(ev.event_type || 'unknown')}</span>
                    <span class="whale-card-time">${timeAgo(ev.timestamp)}</span>
                </div>
                <div class="whale-card-detail">
                    <span class="whale-card-amount">${formatNumber(ev.amount_mnt)} ${escapeHtml(ev.token || 'MNT')}</span>
                    <span class="whale-card-address">${truncateAddr(ev.address)}</span>
                </div>
            </div>
        </div>
    `).join('');
}

function getEventTypeIcon(type) {
    const icons = {
        large_transfer: 'arrow-right-arrow-left',
        dex_buy: 'arrow-trend-up',
        dex_sell: 'arrow-trend-down',
        bridge_in: 'bridge',
        bridge_out: 'bridge-circle-xmark',
    };
    return icons[type] || 'circle-dot';
}

// ── AI Signals ─────────────────────────────────────────────

function renderSignals(signals) {
    const container = document.getElementById('signalsList');
    const counter = document.getElementById('signalCount');
    if (!signals || signals.length === 0) {
        container.innerHTML = '<div class="empty-state"><i class="fas fa-brain"></i>No signals — AI warming up...</div>';
        counter.textContent = '0 signals';
        return;
    }
    counter.textContent = signals.length + ' signals';
    container.innerHTML = signals.slice(0, 8).map(sig => {
        const conf = Math.round((sig.confidence || 0) * 100);
        const confClass = conf >= 75 ? 'high' : conf >= 50 ? 'medium' : 'low';
        return `
        <div class="signal-card">
            <div class="signal-header">
                <span class="signal-token">${escapeHtml(sig.token || '???')}</span>
                <span class="signal-badge ${(sig.action || 'hold')}">
                    <i class="fas fa-${getSignalIcon(sig.action)}"></i>
                    ${(sig.action || 'hold').toUpperCase()}
                </span>
            </div>
            <div class="signal-reasoning">${escapeHtml(sig.reasoning || 'No reasoning provided')}</div>
            <div class="signal-confidence">
                <div class="confidence-bar-bg">
                    <div class="confidence-bar-fill ${confClass}" style="width: ${conf}%"></div>
                </div>
                <span class="confidence-label">${conf}%</span>
            </div>
            <div class="signal-meta">
                <span>Target: $${sig.price_target || '—'}</span>
                <span>${timeAgo(sig.timestamp)}</span>
            </div>
        </div>`;
    }).join('');
}

function getSignalIcon(action) {
    return { buy: 'arrow-trend-up', sell: 'arrow-trend-down', hold: 'minus' }[action] || 'question';
}

// ── DEX Swaps ──────────────────────────────────────────────

function renderSwaps(swaps) {
    const tbody = document.getElementById('swapsTableBody');
    const counter = document.getElementById('swapCount');
    if (!swaps || swaps.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading-cell">No swaps indexed yet</td></tr>';
        counter.textContent = '0 swaps';
        return;
    }
    counter.textContent = swaps.length + ' swaps';
    tbody.innerHTML = swaps.slice(0, 20).map(swap => {
        const dexClass = getDexClass(swap.dex);
        const shortTx = swap.tx_hash ? swap.tx_hash.slice(0, 10) + '…' : '—';
        return `
        <tr>
            <td>
                <span class="swap-dex">
                    <span class="swap-dex-icon ${dexClass}">${(swap.dex || '?')[0]}</span>
                    ${escapeHtml(swap.dex || '—')}
                </span>
            </td>
            <td class="swap-pair">
                ${escapeHtml(swap.token_in || '?')}<span class="arrow">→</span>${escapeHtml(swap.token_out || '?')}
            </td>
            <td class="swap-amount">${formatNumber(swap.amount_in, 4)}</td>
            <td class="swap-wallet">${truncateAddr(swap.sender)}</td>
            <td class="swap-time">${timeAgo(swap.timestamp)}</td>
            <td class="swap-tx">${swap.tx_hash ? `<a href="https://mantlescan.xyz/tx/${swap.tx_hash}" target="_blank">${shortTx}</a>` : '—'}</td>
        </tr>`;
    }).join('');
}

function getDexClass(dex) {
    if (!dex) return 'dex-merchant';
    const lower = dex.toLowerCase();
    if (lower.includes('merchant') || lower.includes('moe')) return 'dex-merchant';
    if (lower.includes('agni')) return 'dex-agni';
    if (lower.includes('fluxion')) return 'dex-fluxion';
    return 'dex-merchant';
}

// ── Anomalies ──────────────────────────────────────────────

function renderAnomalies(reports) {
    const container = document.getElementById('anomaliesList');
    const counter = document.getElementById('anomalyCount');
    if (!reports || reports.length === 0) {
        container.innerHTML = '<div class="empty-state"><i class="fas fa-shield-halved"></i>No anomalies detected</div>';
        counter.textContent = '0 alerts';
        return;
    }
    counter.textContent = reports.length + ' alerts';
    container.innerHTML = reports.slice(0, 6).map(r => `
        <div class="anomaly-card severity-${r.severity || 'medium'}">
            <div class="anomaly-header">
                <span class="anomaly-severity severity-${r.severity || 'medium'}">${(r.severity || 'medium').toUpperCase()}</span>
                <span class="whale-card-time">${timeAgo(r.timestamp)}</span>
            </div>
            <div class="anomaly-summary">${escapeHtml(r.summary || 'Unknown anomaly')}</div>
            <div class="anomaly-meta">
                <span class="anomaly-sentiment ${r.market_sentiment || 'neutral'}">${escapeHtml(r.market_sentiment || 'neutral')}</span>
                <span>Confidence: ${Math.round((r.confidence || 0) * 100)}%</span>
            </div>
        </div>
    `).join('');
}

// ── Protocol Health ────────────────────────────────────────

function renderProtocolHealth(data) {
    const container = document.getElementById('protocolHealth');
    if (!data || !data.protocols) {
        container.innerHTML = '<div class="empty-state"><i class="fas fa-heartbeat"></i>Waiting for protocol data...</div>';
        return;
    }
    let html = data.protocols.map(p => `
        <div class="protocol-card">
            <div class="protocol-logo ${getDexClass(p.name)}">${(p.name || '?')[0]}</div>
            <div class="protocol-info">
                <div class="protocol-name">${escapeHtml(p.name)}</div>
                <div class="protocol-stats">
                    <div>
                        <span class="protocol-stat-label">TVL</span>
                        <span class="protocol-stat-value">${formatUSD(p.tvl)}</span>
                    </div>
                    <div>
                        <span class="protocol-stat-label">24h Vol</span>
                        <span class="protocol-stat-value">${formatUSD(p.volume_24h)}</span>
                    </div>
                    <div>
                        <span class="protocol-stat-label">Pools</span>
                        <span class="protocol-stat-value">${p.pools || '—'}</span>
                    </div>
                </div>
            </div>
            <div class="protocol-change ${(p.change_24h || 0) >= 0 ? 'up' : 'down'}">
                ${(p.change_24h || 0) >= 0 ? '+' : ''}${(p.change_24h || 0).toFixed(2)}%
            </div>
        </div>
    `).join('');

    html += `
        <div class="protocol-total">
            <div class="protocol-total-item">
                <div class="protocol-total-label">Total TVL</div>
                <div class="protocol-total-value">${formatUSD(data.total_tvl)}</div>
            </div>
            <div class="protocol-total-item">
                <div class="protocol-total-label">Total 24h Volume</div>
                <div class="protocol-total-value">${formatUSD(data.total_volume_24h)}</div>
            </div>
        </div>
    `;
    container.innerHTML = html;
}

// ── Stats Bar ──────────────────────────────────────────────

function renderStats(stats) {
    if (!stats) return;
    document.getElementById('statWhaleEvents').textContent = formatNumber(stats.total_whale_events, 0);
    document.getElementById('statActiveSignals').textContent = formatNumber(stats.active_signals, 0);
    document.getElementById('statAnomalies').textContent = formatNumber(stats.anomalies_detected, 0);
    document.getElementById('statMntPrice').textContent = '$' + (stats.mnt_price || '—');
    document.getElementById('statTotalSwaps').textContent = formatNumber(stats.total_swaps, 0);

    const changeEl = document.getElementById('statMntChange');
    if (stats.mnt_price_change_24h != null) {
        const up = stats.mnt_price_change_24h >= 0;
        changeEl.textContent = (up ? '+' : '') + stats.mnt_price_change_24h.toFixed(2) + '%';
        changeEl.className = 'stat-change ' + (up ? 'up' : 'down');
    }
}

// ── Main Refresh Loop ──────────────────────────────────────

async function refreshAll() {
    const [stats, whales, signals, swaps, anomalies, health] = await Promise.all([
        fetchJSON('/api/stats'),
        fetchJSON('/api/whale-events?limit=20'),
        fetchJSON('/api/signals?limit=10'),
        fetchJSON('/api/dex-swaps?limit=30'),
        fetchJSON('/api/anomalies?limit=10'),
        fetchJSON('/api/protocol-health'),
    ]);

    renderStats(stats);
    if (whales) renderWhaleEvents(whales.events);
    if (signals) renderSignals(signals.signals);
    if (swaps) renderSwaps(swaps.swaps);
    if (anomalies) renderAnomalies(anomalies.reports);
    if (health) renderProtocolHealth(health);

    lastRefreshTime = new Date();
    document.getElementById('lastUpdate').textContent = 'Updated ' + lastRefreshTime.toLocaleTimeString();
}

// ── Init ───────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    console.log('🧠 MantleAlpha Dashboard loaded');
    refreshAll();
    setInterval(refreshAll, REFRESH_INTERVAL);
});
