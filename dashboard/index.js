/**
 * Store Intelligence Dashboard — Real-time JavaScript
 * Connects to SSE, renders metrics. Shows nothing until real data arrives.
 */

(function () {
    'use strict';

    let eventSource = null;
    let storeId = 'ST1008';
    const API = window.location.origin;

    // DOM refs
    const el = {
        visitors:     document.getElementById('val-visitors'),
        conversion:   document.getElementById('val-conversion'),
        purchases:    document.getElementById('val-purchases'),
        events:       document.getElementById('val-events'),
        lastUpdate:   document.getElementById('last-update'),
        liveTag:      document.getElementById('live-indicator'),
        storeSelect:  document.getElementById('store-selector'),
        funnelEntry:  document.getElementById('funnel-entry'),
        funnelZone:   document.getElementById('funnel-zone'),
        funnelBilling:document.getElementById('funnel-billing'),
        funnelPurch:  document.getElementById('funnel-purchase'),
        heatmap:      document.getElementById('heatmap-grid'),
        anomalyList:  document.getElementById('anomaly-list'),
        anomalyCount: document.getElementById('anomaly-count'),
        eventFeed:    document.getElementById('event-feed'),
    };

    // ─── Helpers ────────────────────────────────────────────────

    function flash(node, val) {
        const str = String(val);
        if (node.textContent === str) return;
        node.textContent = str;
        node.classList.add('flash');
        setTimeout(() => node.classList.remove('flash'), 300);
    }

    function ts(s) {
        if (!s) return '--:--:--';
        const d = new Date(s);
        return d.toLocaleTimeString('en-IN', {
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
        });
    }

    function heatClass(score) {
        if (score >= 70) return 'hot';
        if (score >= 30) return 'warm';
        return 'cold';
    }

    // ─── SSE ────────────────────────────────────────────────────

    function connect() {
        if (eventSource) eventSource.close();

        eventSource = new EventSource(`${API}/dashboard/stream?store_id=${storeId}`);

        eventSource.addEventListener('metrics', (e) => {
            try { update(JSON.parse(e.data)); }
            catch (err) { console.error('SSE parse error:', err); }
        });

        eventSource.onopen = () => {
            el.liveTag.textContent = 'LIVE';
            el.liveTag.classList.add('connected');
        };

        eventSource.onerror = () => {
            el.liveTag.textContent = 'OFFLINE';
            el.liveTag.classList.remove('connected');
        };
    }

    // ─── Update Dashboard ───────────────────────────────────────

    function update(data) {
        if (data.error) return;

        const visitors = data.unique_visitors || 0;
        const purchases = data.total_purchases || 0;
        const events = data.total_events || 0;
        const rate = data.conversion_rate || 0;

        flash(el.visitors, visitors);
        flash(el.conversion, (rate * 100).toFixed(1) + '%');
        flash(el.purchases, purchases);
        flash(el.events, events);

        el.lastUpdate.textContent = new Date().toLocaleTimeString('en-IN', {
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
        });

        renderHeatmap(data.zones || []);
        renderEventFeed(data.recent_events || []);
        fetchFunnel();
        fetchAnomalies();
    }

    // ─── Heatmap ────────────────────────────────────────────────

    function renderHeatmap(zones) {
        if (!zones.length) {
            el.heatmap.innerHTML = '<p class="empty">NO DATA</p>';
            return;
        }

        const maxV = Math.max(...zones.map(z => z.visits), 1);

        el.heatmap.innerHTML = zones.map(z => {
            const score = (z.visits / maxV) * 100;
            const cls = heatClass(score);
            const dwell = (z.avg_dwell_ms / 1000).toFixed(1);
            return `
                <div class="heatmap-cell ${cls}">
                    <span class="heatmap-zone">${z.zone_id}</span>
                    <span class="heatmap-visits">${z.visits}</span>
                    <span class="heatmap-dwell">${dwell}s avg dwell</span>
                </div>`;
        }).join('');
    }

    // ─── Event Feed ─────────────────────────────────────────────

    function renderEventFeed(events) {
        if (!events.length) {
            el.eventFeed.innerHTML = '<p class="empty">WAITING FOR EVENTS</p>';
            return;
        }

        el.eventFeed.innerHTML = events.map(e => `
            <div class="event-item">
                <span class="event-type">${e.event_type}</span>
                <span class="event-visitor">${e.visitor_id || '—'}</span>
                <span class="event-zone">${e.zone_id || '—'}</span>
                <span class="event-conf">${((e.confidence || 0) * 100).toFixed(0)}%</span>
                <span class="event-time">${ts(e.timestamp)}</span>
            </div>`).join('');
    }

    // ─── Funnel ─────────────────────────────────────────────────

    async function fetchFunnel() {
        try {
            const r = await fetch(`${API}/stores/${storeId}/funnel`);
            if (!r.ok) return;
            const data = await r.json();
            renderFunnel(data.stages || []);
        } catch (_) {}
    }

    function renderFunnel(stages) {
        if (!stages.length) return;
        const max = stages[0]?.count || 1;
        const els = [el.funnelEntry, el.funnelZone, el.funnelBilling, el.funnelPurch];

        stages.forEach((s, i) => {
            if (!els[i]) return;
            const bar = els[i].querySelector('.funnel-bar');
            const count = els[i].querySelector('.funnel-count');
            const drop = els[i].querySelector('.funnel-drop');

            const pct = max > 0 ? Math.max((s.count / max) * 100, 0) : 0;
            bar.style.width = pct + '%';
            count.textContent = s.count;

            if (drop) {
                drop.textContent = s.drop_off_pct > 0 ? `↓${s.drop_off_pct.toFixed(0)}%` : '';
            }
        });
    }

    // ─── Anomalies ──────────────────────────────────────────────

    async function fetchAnomalies() {
        try {
            const r = await fetch(`${API}/stores/${storeId}/anomalies`);
            if (!r.ok) return;
            const data = await r.json();
            renderAnomalies(data.anomalies || []);
        } catch (_) {}
    }

    function renderAnomalies(anomalies) {
        const n = anomalies.length;
        el.anomalyCount.textContent = n;
        el.anomalyCount.className = n > 0 ? 'count-badge active' : 'count-badge';

        if (!n) {
            el.anomalyList.innerHTML = '<p class="empty">NONE DETECTED</p>';
            return;
        }

        el.anomalyList.innerHTML = anomalies.map(a => `
            <div class="anomaly-item">
                <span class="anomaly-severity ${a.severity}">${a.severity}</span>
                <div>
                    <div class="anomaly-desc">${a.description}</div>
                    <div class="anomaly-action">> ${a.suggested_action}</div>
                </div>
            </div>`).join('');
    }

    // ─── Init ───────────────────────────────────────────────────

    el.storeSelect.addEventListener('change', (e) => {
        storeId = e.target.value;
        connect();
    });

    connect();

})();
