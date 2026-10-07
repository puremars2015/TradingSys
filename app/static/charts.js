/*
 * 行情看板共用的 SVG 圖表工具（/foreign-futures、/taiex）。
 * 不依賴外部函式庫；所有外部資料一律用 textContent 寫入 DOM。
 */
(function () {
    const SVG_NS = 'http://www.w3.org/2000/svg';
    const fmt = new Intl.NumberFormat('zh-TW');
    const fmt2 = new Intl.NumberFormat('zh-TW', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const signed = (v, f = fmt) => (v > 0 ? '+' : '') + f.format(v);

    function shortNum(v) {
        const a = Math.abs(v);
        if (a >= 1e8) return (v / 1e8).toFixed(a >= 1e10 ? 0 : 1).replace(/\.0$/, '') + '億';
        if (a >= 10000) return (v / 10000).toFixed(a >= 100000 ? 0 : 1).replace(/\.0$/, '') + '萬';
        return fmt.format(Math.round(v * 100) / 100);
    }

    function svgEl(tag, attrs, parent) {
        const node = document.createElementNS(SVG_NS, tag);
        for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
        if (parent) parent.appendChild(node);
        return node;
    }

    function htmlEl(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }

    function lineKey(color) {
        const key = htmlEl('i', 'key');
        key.style.background = color;
        return key;
    }

    function niceTicks(min, max, count) {
        if (min === max) { min -= 1; max += 1; }
        const raw = (max - min) / count;
        const mag = Math.pow(10, Math.floor(Math.log10(raw)));
        const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw);
        const ticks = [];
        for (let t = Math.floor(min / step) * step; t <= max + step * 0.001; t += step) ticks.push(t);
        if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
        return ticks;
    }

    function tipRow(name, color, valueText) {
        const row = htmlEl('div', 'row');
        row.append(lineKey(color), htmlEl('span', 'name', name), htmlEl('strong', null, valueText));
        return row;
    }

    /**
     * 畫一張單軸圖。
     *
     * series: [{ key, name, color, type: 'line' | 'bar', label: true|false, axis: 'left' | 'right' }]
     *         axis: 'right' 的折線用獨立的右軸刻度（只標數字、不畫格線），長條一律在左軸
     * opts:   { includeZero, valueText(v, s), axisText(v), labelText(v),
     *           xText(r), tipTitle(r),          // 預設 x 軸是 trade_date
     *           grouped,                        // 多組長條並排（預設重疊）
     *           refLines: [{ value, label }],   // 水平參考線
     *           rightAxisText(v),               // 右軸刻度文字
     *           extraTip: [{ name, color, value: r => text }],
     *           onHover(i | null) }                // 滑鼠移動時通知，用來連動其他圖
     *
     * 值為 null 的點在折線上會斷開（例如資料不足的均線）。
     * 回傳 { mark(i), unmark() }：在第 i 筆畫十字線與圓點（不顯示提示框），給連動用。
     */
    function drawChart(svg, tip, rows, series, opts = {}) {
        svg.textContent = '';
        const width = svg.clientWidth || 800;
        const height = svg.clientHeight || 300;
        svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
        const rightSeries = series.filter(s => s.axis === 'right');
        const hasRight = rightSeries.length > 0;
        const m = { top: 12, right: hasRight ? 64 : 56, bottom: 26, left: 56 };
        const w = width - m.left - m.right;
        const h = height - m.top - m.bottom;
        const n = rows.length;
        const hasBars = series.some(s => s.type === 'bar');
        const valueText = opts.valueText || (v => fmt.format(v));
        const axisText = opts.axisText || shortNum;
        const labelText = opts.labelText || shortNum;
        const xText = opts.xText || (r => r.trade_date.slice(5).replace('-', '/'));
        const tipTitle = opts.tipTitle || (r => r.trade_date);
        const refLines = opts.refLines || [];

        const leftSeries = series.filter(s => s.axis !== 'right');
        // fitRange：刻度只依目前視窗內資料的最小/最大值決定（不強制含 0、參考線不撐開刻度）
        const fit = !!opts.fitRange;
        const values = rows.flatMap(r => leftSeries.map(s => r[s.key])).filter(v => v != null)
            .concat(fit ? [] : refLines.map(l => l.value));
        let lo = Math.min(...values), hi = Math.max(...values);
        if (!fit && (opts.includeZero || hasBars)) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
        if (fit) { const pad = (hi - lo) * 0.05 || 1; lo -= pad; hi += pad; }
        const ticks = niceTicks(lo, hi, 5);
        const yMin = ticks[0], yMax = ticks[ticks.length - 1];
        // 長條的基準線：0 在範圍內就從 0 長，否則從最靠近 0 的那一邊長
        const baseV = Math.min(Math.max(0, yMin), yMax);
        // 有長條時用 band 座標，長條才不會超出繪圖區
        const band = w / n;
        const x = hasBars
            ? i => m.left + (i + 0.5) * band
            : i => m.left + (n === 1 ? w / 2 : (i / (n - 1)) * w);
        const y = v => m.top + h - ((v - yMin) / (yMax - yMin)) * h;

        let yRight = y;
        if (hasRight) {
            const rv = rows.flatMap(r => rightSeries.map(s => r[s.key])).filter(v => v != null);
            let rlo = Math.min(...rv), rhi = Math.max(...rv);
            const rpad = (rhi - rlo) * 0.05 || 1;
            const rTicks = niceTicks(rlo - rpad, rhi + rpad, 5);
            const rMin = rTicks[0], rMax = rTicks[rTicks.length - 1];
            yRight = v => m.top + h - ((v - rMin) / (rMax - rMin)) * h;
            const rightAxisText = opts.rightAxisText || shortNum;
            for (const t of rTicks) {
                svgEl('text', { x: m.left + w + 8, y: yRight(t) + 4 }, svg).textContent = rightAxisText(t);
            }
        }
        const yOf = s => (s.axis === 'right' ? yRight : y);

        for (const t of ticks) {
            const isZero = t === 0 && (opts.includeZero || hasBars || fit);
            svgEl('line', { class: isZero ? 'zero' : 'grid', x1: m.left, x2: m.left + w, y1: y(t), y2: y(t) }, svg);
            svgEl('text', { x: m.left - 8, y: y(t) + 4, 'text-anchor': 'end' }, svg).textContent = axisText(t);
        }

        const xTickCount = Math.max(2, Math.min(n, Math.floor(w / 90)));
        for (let k = 0; k < xTickCount; k++) {
            const i = Math.round((k / (xTickCount - 1 || 1)) * (n - 1));
            svgEl('text', {
                x: x(i), y: m.top + h + 18,
                'text-anchor': k === 0 ? 'start' : (k === xTickCount - 1 ? 'end' : 'middle'),
            }, svg).textContent = xText(rows[i]);
        }

        const barSeries = series.filter(s => s.type === 'bar');
        // 長條之間留 2px 底色間隔；資料很密時至少保留 1px 寬
        const gap = band > 4 ? 2 : 0;
        const slots = opts.grouped ? barSeries.length : 1;
        const bw = Math.max(1, (band - gap) / slots - (opts.grouped && band > 8 ? 1 : 0));
        barSeries.forEach((s, k) => {
            const offset = opts.grouped ? (k - (slots - 1) / 2) * ((band - gap) / slots) : 0;
            const radius = bw >= 8 ? 4 : 0;
            rows.forEach((r, i) => {
                const v = r[s.key];
                if (v == null) return;
                const top = y(Math.max(v, baseV)), bottom = y(Math.min(v, baseV));
                svgEl('rect', {
                    x: x(i) + offset - bw / 2, y: top, width: bw, height: Math.max(1, bottom - top),
                    rx: radius, fill: s.color,
                }, svg);
            });
        });

        // 參考線畫在長條之後，才不會被蓋住
        for (const line of refLines) {
            if (line.value < yMin || line.value > yMax) continue;
            svgEl('line', { class: 'ref', x1: m.left, x2: m.left + w, y1: y(line.value), y2: y(line.value) }, svg);
            if (line.label) {
                svgEl('text', { class: 'ref-label', x: m.left + 4, y: y(line.value) - 6 }, svg)
                    .textContent = line.label;
            }
        }

        for (const s of series.filter(s => s.type !== 'bar')) {
            let d = '';
            let pen = 'M';
            rows.forEach((r, i) => {
                const v = r[s.key];
                if (v == null) { pen = 'M'; return; }
                d += `${pen}${x(i).toFixed(1)},${yOf(s)(v).toFixed(1)}`;
                pen = 'L';
            });
            // 疊在長條上的折線先描一圈底色，交錯處才看得清楚
            if (hasBars) svgEl('path', { class: 'line halo', d }, svg);
            svgEl('path', { class: 'line', d, stroke: s.color }, svg);
        }

        // 只在最新一點標數值，不在每個點都標
        // 右軸的數字已經標在軸上，最新值改由提示框與卡片呈現，避免跟刻度擠在一起
        for (const s of series.filter(s => s.label !== false && s.axis !== 'right')) {
            const last = rows[n - 1][s.key];
            if (last == null) continue;
            if (s.type !== 'bar') {
                svgEl('circle', { cx: x(n - 1), cy: y(last), r: 4, fill: s.color, stroke: 'var(--surface-1)', 'stroke-width': 2 }, svg);
            }
            svgEl('text', { class: 'direct-label', x: x(n - 1) + 8, y: y(last) + 4 }, svg).textContent = labelText(last);
        }

        const cross = svgEl('line', { class: 'crosshair', y1: m.top, y2: m.top + h, visibility: 'hidden' }, svg);
        const dots = series.map(s => s.type === 'bar' ? null :
            svgEl('circle', { r: 4, fill: s.color, stroke: 'var(--surface-1)', 'stroke-width': 2, visibility: 'hidden' }, svg));
        const hit = svgEl('rect', { x: m.left, y: m.top, width: w, height: h, fill: 'transparent' }, svg);

        function mark(i) {
            const r = rows[i];
            if (!r) return unmark();
            cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i));
            cross.setAttribute('visibility', 'visible');
            series.forEach((s, j) => {
                if (!dots[j]) return;
                const v = r[s.key];
                dots[j].setAttribute('visibility', v == null ? 'hidden' : 'visible');
                if (v != null) { dots[j].setAttribute('cx', x(i)); dots[j].setAttribute('cy', yOf(s)(v)); }
            });
        }
        function unmark() {
            cross.setAttribute('visibility', 'hidden');
            dots.forEach(d => d && d.setAttribute('visibility', 'hidden'));
        }

        function show(evt) {
            const rect = svg.getBoundingClientRect();
            const px = (evt.clientX - rect.left) * (width / rect.width);
            const i = hasBars
                ? Math.max(0, Math.min(n - 1, Math.floor((px - m.left) / band)))
                : Math.max(0, Math.min(n - 1, Math.round(((px - m.left) / w) * (n - 1))));
            const r = rows[i];
            mark(i);
            if (opts.onHover) opts.onHover(i);

            tip.textContent = '';
            tip.appendChild(htmlEl('div', 'date', tipTitle(r)));
            for (const s of series) {
                if (r[s.key] != null) tip.appendChild(tipRow(s.name, s.color, valueText(r[s.key], s)));
            }
            for (const extra of opts.extraTip || []) {
                tip.appendChild(tipRow(extra.name, extra.color, extra.value(r)));
            }

            tip.style.display = 'block';
            const card = svg.parentElement.getBoundingClientRect();
            const left = evt.clientX - card.left + 14;
            tip.style.left = Math.min(left, card.width - tip.offsetWidth - 8) + 'px';
            tip.style.top = (rect.top - card.top + 8) + 'px';
        }
        function hide() {
            tip.style.display = 'none';
            unmark();
            if (opts.onHover) opts.onHover(null);
        }
        hit.addEventListener('pointermove', show);
        hit.addEventListener('pointerdown', show);
        hit.addEventListener('pointerleave', hide);
        return { mark, unmark };
    }

    /** tiles: [{ label, color?, value, delta?, small? }] */
    function renderTiles(container, tiles) {
        container.textContent = '';
        for (const t of tiles) {
            const tile = htmlEl('div', 'tile');
            const label = htmlEl('div', 'label');
            if (t.color) label.appendChild(lineKey(t.color));
            label.appendChild(document.createTextNode(t.label));
            tile.append(label, htmlEl('div', t.small ? 'value small' : 'value', t.value));
            if (t.delta != null) tile.appendChild(htmlEl('div', 'delta', t.delta));
            container.appendChild(tile);
        }
    }

    /** 由新到舊列出；cells(row, prevRow) 回傳該列每格文字。 */
    function renderTable(tbody, rows, cells) {
        tbody.textContent = '';
        for (let i = rows.length - 1; i >= 0; i--) {
            const tr = document.createElement('tr');
            for (const c of cells(rows[i], rows[i - 1])) tr.appendChild(htmlEl('td', null, c));
            tbody.appendChild(tr);
        }
    }

    /** 以最後一筆的日期為基準往回取 days 天；days 為 0 表示全部。 */
    function filterByDays(rows, days) {
        if (!days || !rows.length) return rows;
        const last = new Date(rows[rows.length - 1].trade_date);
        const since = new Date(last.getTime() - days * 86400000).toISOString().slice(0, 10);
        return rows.filter(r => r.trade_date >= since);
    }

    /** 綁定 .filters 時間範圍按鈕與視窗縮放；render(days) 會在變動時被呼叫。 */
    function bindRange(render, initialDays) {
        let days = initialDays;
        document.querySelectorAll('.filters button').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.filters button').forEach(b => b.setAttribute('aria-pressed', 'false'));
                btn.setAttribute('aria-pressed', 'true');
                days = Number(btn.dataset.days);
                render(days);
            });
        });
        let timer;
        window.addEventListener('resize', () => {
            clearTimeout(timer);
            timer = setTimeout(() => render(days), 150);
        });
        return () => days;
    }

    function showEmpty(svgIds, hint) {
        for (const id of svgIds) {
            const svg = document.getElementById(id);
            svg.style.display = 'none';
            if (svg.nextElementSibling && svg.nextElementSibling.classList.contains('empty')) continue;
            const empty = htmlEl('div', 'empty', '目前還沒有資料。服務啟動後會自動往回補一年，也可以手動執行：');
            empty.appendChild(document.createElement('br'));
            empty.appendChild(htmlEl('code', null, hint));
            svg.after(empty);
        }
    }

    window.MarketCharts = {
        fmt, fmt2, signed, shortNum, drawChart, renderTiles, renderTable, filterByDays, bindRange, showEmpty,
    };
})();
