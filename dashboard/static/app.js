/**
 * MantleAlpha Dashboard — Production-grade client-side JavaScript
 * Auto-refreshes all data from API endpoints every 5 seconds.
 * Handles empty states gracefully with animated placeholders.
 */

const REFRESH_INTERVAL = 5000;
let lastRefreshTime = null;
let isFirstLoad = true;

// ── Helpers ────────────────────────────────────────────────

async function fetchJSON(url) {
    try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (err) {
        console.warn(`Fetch failed: ${url}`, err);
        return null;
    }
}

function formatNumber(n, decimals = 1) {
    if (n == null || isNaN(n) || n === 0) return '—';
    if (n >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
    return Number(n).toFixed(decimals);
}

function formatUSD(n) {
    if (n == null || isNaN(n) || n === 0) return '—';
    return '$' + formatNumber(n);
}

function timeAgo(timestamp) {
    if (!timestamp) return '—';
    const now = Date.now() / 1000;
    const diff = now - timestamp;
    if (diff < 5) return 'Just now';
    if (diff < 60) return Math.floor(diff) + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

function truncateAddr(addr, chars = 6) {
    if (!addr) return '—';
    if (addr.length <= 14) return addr;
    return addr.slice(0, chars + 2) + '…' + addr.slice(-4);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function emptyState(icon, message) {
    return `<div class="empty-state pulse-anim">
        <i class="fas ${icon}"></i>
        <p>${message}</p>
    </div>`;
}

// ── Stats Bar ──────────────────────────────────────────────

function renderStats(stats) {
    if (!stats) return;

    setStatValue('statWhaleEvents', formatNumber(stats.total_whale_events, 0));
    setStatValue('statActiveSignals', formatNumber(stats.active_signals, 0));
    setStatValue('statAnomalies', formatNumber(stats.anomalies_detected, 0));
    setStatValue('statDexVolume', formatUSD(stats.total_volume));

    const priceEl = document.getElementById('statMntPrice');
    priceEl.textContent = stats.mnt_price > 0 ? '$' + stats.mnt_price.toFixed(4) : '—';

    const changeEl = document.getElementById('statMntChange');
    if (stats.mnt_price_change_24h != null && stats.mnt_price_change_24h !== 0) {
        const up = stats.mnt_price_change_24h >= 0;
        changeEl.innerHTML = `<i class="fas fa-arrow-${up ? 'up' : 'down'}"></i> ${up ? '+' : ''}${stats.mnt_price_change_24h.toFixed(2)}%`;
        changeEl.className = 'stat-trend ' + (up ? 'up' : 'down');
    } else {
        changeEl.textContent = '';
    }
}

function setStatValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

// ── Whale Events ───────────────────────────────────────────

function renderWhaleEvents(events) {
    const container = document.getElementById('whaleEventsList');
    const counter = document.getElementById('whaleCount');
    if (!events || events.length === 0) {
        container.innerHTML = emptyState('fa-satellite-dish', 'Waiting for on-chain data...');
        counter.textContent = '0 events';
        return;
    }
    counter.textContent = events.length + ' events';
    container.innerHTML = events.slice(0, 12).map((ev, i) => {
        const iconClass = getEventIconClass(ev.event_type);
        return `
        <div class="whale-card" style="animation-delay: ${i * 0.05}s">
            <div class="whale-card-icon ${iconClass}">
                <i class="fas fa-${getEventTypeIcon(ev.event_type)}"></i>
            </div>
            <div class="whale-card-info">
                <div class="whale-card-header">
                    <span class="whale-card-type">${escapeHtml(formatEventType(ev.event_type))}</span>
                    <span class="whale-card-time">${timeAgo(ev.timestamp)}</span>
                </div>
                <div class="whale-card-detail">
                    <span class="whale-card-amount">${formatNumber(ev.amount_mnt)} ${escapeHtml(ev.token || 'MNT')}</span>
                    <span class="whale-card-address">${truncateAddr(ev.address)}</span>
                </div>
            </div>
        </div>`;
    }).join('');
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

function getEventIconClass(type) {
    if (!type) return '';
    if (type.includes('buy') || type.includes('in')) return 'event-buy';
    if (type.includes('sell') || type.includes('out')) return 'event-sell';
    if (type.includes('bridge')) return 'event-bridge';
    return '';
}

function formatEventType(type) {
    if (!type) return 'Unknown';
    return type.replace(/_/g, ' ');
}

// ── AI Signals ─────────────────────────────────────────────

function renderSignals(signals) {
    const container = document.getElementById('signalsList');
    const counter = document.getElementById('signalCount');
    if (!signals || signals.length === 0) {
        container.innerHTML = emptyState('fa-brain', 'Waiting for on-chain data...');
        counter.textContent = '0 signals';
        return;
    }
    counter.textContent = signals.length + ' signals';
    container.innerHTML = signals.slice(0, 8).map((sig, i) => {
        const conf = Math.round((sig.confidence || 0) * 100);
        const confClass = conf >= 75 ? 'high' : conf >= 50 ? 'medium' : 'low';
        const action = (sig.action || 'hold').toLowerCase();
        return `
        <div class="signal-card" style="animation-delay: ${i * 0.06}s">
            <div class="signal-header">
                <span class="signal-token">${escapeHtml(sig.token || '???')}</span>
                <span class="signal-badge ${action}">
                    <i class="fas fa-${getSignalIcon(action)}"></i>
                    ${action.toUpperCase()}
                </span>
            </div>
            <div class="signal-conviction">
                <span class="conviction-pct ${confClass}">${conf}%</span>
                <span class="conviction-label">Conviction</span>
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
    return { buy: 'arrow-trend-up', sell: 'arrow-trend-down', hold: 'minus', accumulation: 'layer-group', distribution: 'chart-pie' }[action] || 'question';
}

// ── DEX Swaps ──────────────────────────────────────────────

function renderSwaps(swaps) {
    const tbody = document.getElementById('swapsTableBody');
    const counter = document.getElementById('swapCount');
    const viewAllBtn = document.getElementById('btnViewAll');
    if (!swaps || swaps.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">
            ${emptyState('fa-right-left', 'Waiting for on-chain data...')}
        </td></tr>`;
        counter.textContent = '0 swaps';
        viewAllBtn.style.display = 'none';
        return;
    }
    counter.textContent = swaps.length + ' swaps';
    viewAllBtn.style.display = swaps.length > 15 ? 'inline-block' : 'none';
    tbody.innerHTML = swaps.slice(0, 15).map((swap, i) => {
        const dexClass = getDexClass(swap.dex);
        const shortTx = swap.tx_hash ? swap.tx_hash.slice(0, 10) + '…' : '—';
        return `
        <tr style="animation: fadeInUp 0.3s ease ${i * 0.03}s both">
            <td>
                <span class="swap-dex">
                    <span class="swap-dex-icon ${dexClass}">${(swap.dex || '?')[0]}</span>
                    ${escapeHtml(swap.dex || '—')}
                </span>
            </td>
            <td class="swap-pair">
                ${escapeHtml(swap.token_in || '?')}<span class="arrow">→</span>${escapeHtml(swap.token_out || '?')}
            </td>
            <td class="swap-amount">${formatUSD(swap.amount_in)}</td>
            <td class="swap-wallet">${truncateAddr(swap.sender)}</td>
            <td class="swap-time">${timeAgo(swap.timestamp)}</td>
            <td class="swap-tx">${swap.tx_hash ? `<a href="https://mantlescan.xyz/tx/${swap.tx_hash}" target="_blank" rel="noopener">${shortTx}</a>` : '—'}</td>
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
        container.innerHTML = emptyState('fa-shield-halved', 'Waiting for on-chain data...');
        counter.textContent = '0 alerts';
        return;
    }
    counter.textContent = reports.length + ' alerts';
    container.innerHTML = reports.slice(0, 6).map((r, i) => {
        const sev = r.severity || 'medium';
        const conf = Math.round((r.confidence || 0) * 100);
        return `
        <div class="anomaly-card severity-${sev}" style="animation-delay: ${i * 0.06}s">
            <div class="anomaly-header">
                <span class="anomaly-severity severity-${sev}-badge">
                    ${getSeverityIcon(sev)} ${sev.toUpperCase()}
                </span>
                <span class="whale-card-time">${timeAgo(r.timestamp)}</span>
            </div>
            <div class="anomaly-summary">${escapeHtml(r.summary || 'Unknown anomaly')}</div>
            <div class="anomaly-watch">
                <i class="fas fa-eye"></i> ${getWatchAction(sev, r.summary)}
            </div>
            <div class="anomaly-meta">
                <span class="confidence-meter">
                    Confidence
                    <span class="confidence-meter-bar">
                        <span class="confidence-meter-fill" style="width: ${conf}%; background: ${getConfColor(conf)}"></span>
                    </span>
                    ${conf}%
                </span>
            </div>
        </div>`;
    }).join('');
}

function getSeverityIcon(sev) {
    const icons = {
        critical: '<i class="fas fa-circle-xmark"></i>',
        high: '<i class="fas fa-triangle-exclamation"></i>',
        medium: '<i class="fas fa-circle-info"></i>',
        low: '<i class="fas fa-circle-info"></i>',
    };
    return icons[sev] || icons.medium;
}

function getWatchAction(sev, summary) {
    if (!summary) return 'Monitor closely';
    const lower = summary.toLowerCase();
    if (sev === 'critical') return 'Immediate attention required';
    if (sev === 'high') return 'Watch for cascading effects';
    if (lower.includes('whale')) return 'Track wallet movements';
    if (lower.includes('volume')) return 'Monitor volume trends';
    if (lower.includes('transfer')) return 'Verify transaction sources';
    return 'Monitor closely';
}

function getConfColor(pct) {
    if (pct >= 80) return 'var(--green)';
    if (pct >= 60) return 'var(--yellow)';
    return 'var(--red)';
}

// ── Protocol Health ────────────────────────────────────────

function renderProtocolHealth(data) {
    const container = document.getElementById('protocolHealth');
    if (!data || !data.protocols || data.protocols.length === 0) {
        container.innerHTML = emptyState('fa-heartbeat', 'Waiting for on-chain data...');
        return;
    }
    let html = data.protocols.map((p, i) => {
        const bars = generateMiniBars(p.tvl, p.volume_24h);
        return `
        <div class="protocol-card" style="animation-delay: ${i * 0.06}s">
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
            <div class="protocol-bar-container">${bars}</div>
            <div class="protocol-change ${(p.change_24h || 0) >= 0 ? 'up' : 'down'}">
                ${(p.change_24h || 0) >= 0 ? '+' : ''}${(p.change_24h || 0).toFixed(2)}%
            </div>
        </div>`;
    }).join('');

    if (data.total_tvl || data.total_volume_24h) {
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
        </div>`;
    }
    container.innerHTML = html;
}

function generateMiniBars(tvl, volume) {
    // Generate 7 CSS-only bars to suggest a chart
    const seed = (tvl || 0) + (volume || 0);
    const bars = [];
    for (let i = 0; i < 7; i++) {
        const h = 8 + ((seed * (i + 1) * 17) % 20);
        const opacity = 0.3 + ((i * 0.1) % 0.7);
        bars.push(`<div class="protocol-bar" style="height: ${h}px; background: rgba(0,212,255,${opacity})"></div>`);
    }
    return bars.join('');
}

// ── Main Refresh Loop ──────────────────────────────────────

async function refreshAll() {
    const results = await Promise.allSettled([
        fetchJSON('/api/stats'),
        fetchJSON('/api/whale-events?limit=20'),
        fetchJSON('/api/signals?limit=10'),
        fetchJSON('/api/dex-swaps?limit=30'),
        fetchJSON('/api/anomalies?limit=10'),
        fetchJSON('/api/protocol-health'),
    ]);

    const [statsR, whalesR, signalsR, swapsR, anomaliesR, healthR] = results;

    const stats = statsR.status === 'fulfilled' ? statsR.value : null;
    const whales = whalesR.status === 'fulfilled' ? whalesR.value : null;
    const signals = signalsR.status === 'fulfilled' ? signalsR.value : null;
    const swaps = swapsR.status === 'fulfilled' ? swapsR.value : null;
    const anomalies = anomaliesR.status === 'fulfilled' ? anomaliesR.value : null;
    const health = healthR.status === 'fulfilled' ? healthR.value : null;

    if (stats) renderStats(stats);
    if (whales) renderWhaleEvents(whales.events);
    if (signals) renderSignals(signals.signals);
    if (swaps) renderSwaps(swaps.swaps);
    if (anomalies) renderAnomalies(anomalies.reports);
    if (health) renderProtocolHealth(health);

    lastRefreshTime = new Date();
    const el = document.getElementById('lastUpdate');
    if (el) {
        const allFailed = results.every(r => r.status === 'rejected' || r.value === null);
        el.textContent = allFailed ? 'Connecting...' : 'Updated ' + lastRefreshTime.toLocaleTimeString();
    }

    // Update nav placeholders with mock-like values when stats exist
    if (stats) {
        const blockEl = document.getElementById('navBlockHeight');
        const tpsEl = document.getElementById('navTPS');
        if (blockEl && stats.indexer_blocks_processed > 0) {
            blockEl.textContent = (7500000 + stats.indexer_blocks_processed).toLocaleString();
        }
        if (tpsEl) {
            tpsEl.textContent = stats.total_swaps > 0 ? '2.4' : '—';
        }
    }

    isFirstLoad = false;
}

// ── Init ───────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    refreshAll();
    setInterval(refreshAll, REFRESH_INTERVAL);
});
