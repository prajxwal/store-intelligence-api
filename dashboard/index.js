/**
 * Store Intelligence Dashboard — Real-time JavaScript
 * Connects to SSE endpoint and updates dashboard metrics live.
 */

(function () {
    'use strict';

    // ─── State ──────────────────────────────────────────────────────────
    let eventSource = null;
    let storeId = 'ST1008';
    const API_BASE = window.location.origin;

    // ─── DOM References ─────────────────────────────────────────────────
    const els = {
        visitors: document.getElementById('val-visitors'),
        conversion: document.getElementById('val-conversion'),
        purchases: document.getElementById('val-purchases'),
        events: document.getElementById('val-events'),
        lastUpdate: document.getElementById('last-update'),
        connectionText: document.getElementById('connection-text'),
        connectionBadge: document.getElementById('connection-status'),
        storeSelector: document.getElementById('store-selector'),
        funnelEntry: document.getElementById('funnel-entry'),
        funnelZone: document.getElementById('funnel-zone'),
        funnelBilling: document.getElementById('funnel-billing'),
        funnelPurchase: document.getElementById('funnel-purchase'),
        heatmapGrid: document.getElementById('heatmap-grid'),
        anomalyList: document.getElementById('anomaly-list'),
        anomalyCount: document.getElementById('anomaly-count'),
        eventFeed: document.getElementById('event-feed'),
    };

    // ─── Utilities ──────────────────────────────────────────────────────

    function animateValue(el, newValue) {
        const current = el.textContent;
        if (current !== newValue) {
            el.textContent = newValue;
            el.classList.add('updating');
            setTimeout(() => el.classList.remove('updating'), 600);
        }
    }

    function formatTime(ts) {
        if (!ts) return '—';
        const d = new Date(ts);
        return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    function getHeatColor(score) {
        // Gradient from cool blue to hot red
        if (score >= 80) return 'rgba(239, 68, 68, 0.7)';
        if (score >= 60) return 'rgba(249, 115, 22, 0.6)';
        if (score >= 40) return 'rgba(234, 179, 8, 0.5)';
        if (score >= 20) return 'rgba(34, 197, 94, 0.4)';
        return 'rgba(59, 130, 246, 0.3)';
    }

    function getConfidenceClass(c) {
        if (c >= 0.8) return 'high';
        if (c >= 0.5) return 'medium';
        return 'low';
    }

    // ─── SSE Connection ─────────────────────────────────────────────────

    function connectSSE() {
        if (eventSource) {
            eventSource.close();
        }

        const url = `${API_BASE}/dashboard/stream?store_id=${storeId}`;
        eventSource = new EventSource(url);

        eventSource.addEventListener('metrics', (e) => {
            try {
                const data = JSON.parse(e.data);
                updateDashboard(data);
            } catch (err) {
                console.error('Failed to parse SSE data:', err);
            }
        });

        eventSource.onopen = () => {
            els.connectionText.textContent = 'Connected';
            els.connectionBadge.className = 'connection-badge connected';
        };

        eventSource.onerror = () => {
            els.connectionText.textContent = 'Reconnecting...';
            els.connectionBadge.className = 'connection-badge disconnected';
        };
    }

    // ─── Dashboard Update ───────────────────────────────────────────────

    function updateDashboard(data) {
        if (data.error) return;

        // KPI Cards
        animateValue(els.visitors, String(data.unique_visitors || 0));
        animateValue(els.conversion, ((data.conversion_rate || 0) * 100).toFixed(1) + '%');
        animateValue(els.purchases, String(data.total_purchases || 0));
        animateValue(els.events, String(data.total_events || 0));

        // Last update
        els.lastUpdate.textContent = `Updated: ${new Date().toLocaleTimeString()}`;

        // Zone Heatmap
        updateHeatmap(data.zones || []);

        // Live Event Feed
        updateEventFeed(data.recent_events || []);

        // Fetch funnel and anomalies from API
        fetchFunnel();
        fetchAnomalies();
    }

    function updateHeatmap(zones) {
        if (!zones.length) return;

        const maxVisits = Math.max(...zones.map(z => z.visits), 1);
        
        els.heatmapGrid.innerHTML = zones.map(z => {
            const score = (z.visits / maxVisits) * 100;
            const color = getHeatColor(score);
            const dwellSec = (z.avg_dwell_ms / 1000).toFixed(1);
            return `
                <div class="heatmap-cell" style="background: ${color};">
                    <div class="heatmap-zone-name">${z.zone_id}</div>
                    <div class="heatmap-visits">${z.visits}</div>
                    <div class="heatmap-dwell">${dwellSec}s avg dwell</div>
                </div>
            `;
        }).join('');
    }

    function updateEventFeed(events) {
        if (!events.length) return;

        els.eventFeed.innerHTML = events.map(e => {
            const confClass = getConfidenceClass(e.confidence || 0);
            return `
                <div class="event-item ${e.event_type}">
                    <span class="event-type-badge">${e.event_type}</span>
                    <span class="event-visitor">${e.visitor_id || '—'}</span>
                    <span class="event-zone">${e.zone_id || '—'}</span>
                    <span class="event-confidence ${confClass}">${((e.confidence || 0) * 100).toFixed(0)}%</span>
                    <span class="event-time">${formatTime(e.timestamp)}</span>
                </div>
            `;
        }).join('');
    }

    // ─── API Fetchers ───────────────────────────────────────────────────

    async function fetchFunnel() {
        try {
            const res = await fetch(`${API_BASE}/stores/${storeId}/funnel`);
            if (!res.ok) return;
            const data = await res.json();
            updateFunnel(data.stages || []);
        } catch (e) {
            // Silently fail — funnel will update on next cycle
        }
    }

    function updateFunnel(stages) {
        if (!stages.length) return;

        const maxCount = stages[0]?.count || 1;
        const funnelEls = [els.funnelEntry, els.funnelZone, els.funnelBilling, els.funnelPurchase];

        stages.forEach((stage, i) => {
            if (!funnelEls[i]) return;
            const bar = funnelEls[i].querySelector('.funnel-bar');
            const count = funnelEls[i].querySelector('.funnel-count');
            const dropOff = funnelEls[i].querySelector('.drop-off');

            const pct = maxCount > 0 ? Math.max((stage.count / maxCount) * 100, 15) : 15;
            bar.style.width = pct + '%';
            count.textContent = stage.count;

            if (dropOff && stage.drop_off_pct > 0) {
                dropOff.textContent = `↓${stage.drop_off_pct.toFixed(1)}%`;
            } else if (dropOff) {
                dropOff.textContent = '';
            }
        });
    }

    async function fetchAnomalies() {
        try {
            const res = await fetch(`${API_BASE}/stores/${storeId}/anomalies`);
            if (!res.ok) return;
            const data = await res.json();
            updateAnomalies(data.anomalies || []);
        } catch (e) {
            // Silently fail
        }
    }

    function updateAnomalies(anomalies) {
        const count = anomalies.length;
        els.anomalyCount.textContent = count;
        els.anomalyCount.className = count > 0 ? 'anomaly-badge' : 'anomaly-badge clear';

        if (!count) {
            els.anomalyList.innerHTML = '<p class="placeholder-text">✅ No anomalies detected</p>';
            return;
        }

        els.anomalyList.innerHTML = anomalies.map(a => {
            const severityClass = a.severity === 'WARN' ? 'warn' : a.severity === 'INFO' ? 'info' : '';
            return `
                <div class="anomaly-item ${severityClass}">
                    <span class="anomaly-severity ${a.severity}">${a.severity}</span>
                    <div>
                        <div class="anomaly-desc">${a.description}</div>
                        <div class="anomaly-action">💡 ${a.suggested_action}</div>
                    </div>
                </div>
            `;
        }).join('');
    }

    // ─── Event Listeners ────────────────────────────────────────────────

    els.storeSelector.addEventListener('change', (e) => {
        storeId = e.target.value;
        connectSSE();
    });

    // ─── Initialize ─────────────────────────────────────────────────────

    connectSSE();

})();
