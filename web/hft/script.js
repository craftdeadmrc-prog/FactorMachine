var hftOverviewData = [];
var hftRenderedCount = 0;
var hftCurrentSymbol = '';
var hftActiveToken = 0;
var hftCanvasObserver = null;
var hftRows = [];
var hftViewStart = 0;
var hftViewEnd = 0;
var hftDragState = null;
var hftPriceViewMin = null;
var hftPriceViewMax = null;
var hftDrawFrame = null;
var hftPendingDraw = null;
var hftNavigatorRect = null;
var hftNavigatorDrag = null;
var hftPriceAxisDrag = null;
var hftRenderCache = {
    key: '',
    canvas: null,
    info: null
};
var hftOrderbookLevels = {
    ask: [],
    bid: []
};
var hftOrderbookStats = {
    askTotalQ05: 0,
    askTotalQ15: 0,
    askTotalQ85: 0,
    askTotalQ95: 0,
    bidTotalQ05: 0,
    bidTotalQ15: 0,
    bidTotalQ85: 0,
    bidTotalQ95: 0
};

var hftQuery = {
    market: '',
    interval: '',
    symbol: '',
    adj: 'none',
    mode: 'line',
    threshold: null,
    start_date: null,
    end_date: null
};

function toHftYmd(value) {
    var year = value.getFullYear();
    var month = String(value.getMonth() + 1).padStart(2, '0');
    var day = String(value.getDate()).padStart(2, '0');
    return year + '-' + month + '-' + day;
}

function isCompleteHftDate(value) {
    var text = String(value || '').trim();
    if (!text) return true;
    var match = text.match(/^([1|2]\d{3})-(\d{2})-(\d{2})$/);
    if (!match) return false;

    var date = new Date(text + 'T00:00:00');
    return !Number.isNaN(date.getTime())
        && date.getFullYear() === Number(match[1])
        && date.getMonth() + 1 === Number(match[2])
        && date.getDate() === Number(match[3]);
}

function hasCompleteHftDateRange() {
    var startInput = document.getElementById('hft-start-date');
    var endInput = document.getElementById('hft-end-date');
    if (startInput?.validity?.badInput || endInput?.validity?.badInput) return false;
    return isCompleteHftDate(startInput?.value) && isCompleteHftDate(endInput?.value);
}

function applyHftPresetRange(preset) {
    var startInput = document.getElementById('hft-start-date');
    var endInput = document.getElementById('hft-end-date');
    if (!startInput || !endInput) return;

    var end = new Date();
    var start = null;
    if (preset === '1w') start = new Date(end.getFullYear(), end.getMonth(), end.getDate() - 7);
    if (preset === '1m') start = new Date(end.getFullYear(), end.getMonth(), end.getDate() - 30);
    if (preset === '1y') start = new Date(end.getFullYear() - 1, end.getMonth(), end.getDate());

    startInput.value = start ? toHftYmd(start) : '';
    endInput.value = toHftYmd(end);
}

function getAllowedHftModes(interval) {
    if (interval === '1t') return ['line', 'orderbook'];
    return ['line', 'cusum', 'volume'];
}

function setHftModeOptions() {
    var interval = document.getElementById('hft-interval')?.value || '';
    var select = document.getElementById('hft-bar-mode');
    if (!select) return;

    var allowedModes = getAllowedHftModes(interval);
    var previousMode = hftQuery.mode;
    select.innerHTML = '';

    allowedModes.forEach(function(mode) {
        var option = document.createElement('option');
        option.value = mode;
        option.innerText = mode;
        select.appendChild(option);
    });

    hftQuery.mode = allowedModes.includes(previousMode) ? previousMode : allowedModes[0];
    select.value = hftQuery.mode;
    onHftModeChange();
}

function onHftModeChange() {
    var select = document.getElementById('hft-bar-mode');
    var thresholdGroup = document.getElementById('hft-threshold-group');
    var thresholdInput = document.getElementById('hft-threshold');
    if (!select || !thresholdGroup || !thresholdInput) return;

    var mode = select.value;
    if (mode === 'line' || mode === 'orderbook') {
        thresholdGroup.style.display = 'none';
        thresholdInput.value = '';
        hftQuery.threshold = null;
        return;
    }

    thresholdGroup.style.display = 'block';
    if (mode === 'volume') {
        thresholdInput.value = '1000000';
        thresholdInput.placeholder = '1000000';
    } else {
        thresholdInput.value = '0.02';
        thresholdInput.placeholder = '0.02';
    }
}

function updateHftQuery(symbol, fromPreset) {
    var rangeSelect = document.getElementById('hft-range');
    if (fromPreset === true && rangeSelect) applyHftPresetRange(rangeSelect.value || '1m');

    hftQuery.market = document.getElementById('hft-market')?.value || '';
    hftQuery.interval = document.getElementById('hft-interval')?.value || '';
    hftQuery.symbol = symbol || hftCurrentSymbol || (document.getElementById('hft-symbol-manual')?.value || '').trim();
    hftQuery.adj = document.getElementById('hft-adj')?.value || 'none';
    hftQuery.mode = document.getElementById('hft-bar-mode')?.value || 'line';
    hftQuery.start_date = document.getElementById('hft-start-date')?.value || null;
    hftQuery.end_date = document.getElementById('hft-end-date')?.value || null;

    var thresholdValue = document.getElementById('hft-threshold')?.value;
    if (hftQuery.mode === 'cusum' || hftQuery.mode === 'volume') hftQuery.threshold = Number(thresholdValue);
    else hftQuery.threshold = null;
}

function refreshHftOrderbookLevels(rows) {
    var askLevels = new Set();
    var bidLevels = new Set();
    rows.forEach(function(item) {
        Object.keys(item).forEach(function(key) {
            var match = key.match(/^([ab])(\d+)_[pv]$/);
            if (!match) return;
            if (match[1] === 'a') askLevels.add(Number(match[2]));
            else bidLevels.add(Number(match[2]));
        });
    });
    hftOrderbookLevels.ask = Array.from(askLevels).sort(function(a, b) { return a - b; });
    hftOrderbookLevels.bid = Array.from(bidLevels).sort(function(a, b) { return a - b; });
}

function normalizeHftRows(rows) {
    refreshHftOrderbookLevels(rows);
    return rows.map(function(item) {
        var row = {
            date: String(item.date),
            open: Number(item.open),
            high: Number(item.high),
            low: Number(item.low),
            close: Number(item.close),
            volume: Number(item.volume),
            ticks: Number(item.trade_num),
            action: String(item.action)
        };
        hftOrderbookLevels.ask.forEach(function(level) {
            row['a' + level + '_p'] = Number(item['a' + level + '_p']);
            row['a' + level + '_v'] = Number(item['a' + level + '_v']);
        });
        hftOrderbookLevels.bid.forEach(function(level) {
            row['b' + level + '_p'] = Number(item['b' + level + '_p']);
            row['b' + level + '_v'] = Number(item['b' + level + '_v']);
        });
        return row;
    }).filter(function(item) {
        return Number.isFinite(item.open);
    });
}

function capOrderbookRange() {
    if (hftQuery.mode !== 'orderbook') return;
    var startInput = document.getElementById('hft-start-date');
    var endInput = document.getElementById('hft-end-date');
    if (!startInput || !endInput || !startInput.value || !endInput.value) return;
    var startDate = new Date(startInput.value + 'T00:00:00');
    var endDate = new Date(endInput.value + 'T00:00:00');
    if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime()) || endDate < startDate) return;
    var diffDays = Math.floor((endDate - startDate) / 86400000);
    if (diffDays <= 365) return;
    var nextStartDate = new Date(endDate.getFullYear(), endDate.getMonth(), endDate.getDate() - 365);
    startInput.value = toHftYmd(nextStartDate);
    hftQuery.start_date = startInput.value;
}

function formatHftDateTimeToSecond(raw) {
    var text = String(raw || '').trim();
    if (!text) return '';
    var normalized = text.replace('T', ' ');
    var matched = normalized.match(/^(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}:\d{2}))?/);
    if (matched) return matched[1] + (matched[2] ? (' ' + matched[2]) : '');
    var date = new Date(text);
    if (!Number.isNaN(date.getTime())) {
        var year = date.getFullYear();
        var month = String(date.getMonth() + 1).padStart(2, '0');
        var day = String(date.getDate()).padStart(2, '0');
        var hour = String(date.getHours()).padStart(2, '0');
        var minute = String(date.getMinutes()).padStart(2, '0');
        var second = String(date.getSeconds()).padStart(2, '0');
        return year + '-' + month + '-' + day + ' ' + hour + ':' + minute + ':' + second;
    }
    return normalized;
}

function resetHftViewWindow() {
    hftViewStart = 0;
    hftViewEnd = hftRows.length;
    hftPriceViewMin = null;
    hftPriceViewMax = null;
}

function ensureHftPriceWindowValid(baseMinValue, baseMaxValue) {
    if (!Number.isFinite(baseMinValue) || !Number.isFinite(baseMaxValue)) return;
    if (baseMaxValue <= baseMinValue) {
        var padding = Math.max(1, Math.abs(baseMaxValue) * 0.01);
        baseMinValue -= padding;
        baseMaxValue += padding;
    }
    if (!Number.isFinite(hftPriceViewMin) || !Number.isFinite(hftPriceViewMax) || hftPriceViewMax <= hftPriceViewMin) {
        hftPriceViewMin = baseMinValue;
        hftPriceViewMax = baseMaxValue;
    }
}

function ensureHftWindowValid() {
    var total = hftRows.length;
    if (!total) {
        hftViewStart = 0;
        hftViewEnd = 0;
        return;
    }
    if (hftViewEnd <= hftViewStart) {
        hftViewStart = 0;
        hftViewEnd = total;
    }
    var windowSize = hftViewEnd - hftViewStart;
    if (total > 1 && windowSize < 2) windowSize = 2;
    windowSize = Math.min(total, windowSize);
    hftViewStart = Math.max(0, Math.min(total - windowSize, hftViewStart));
    hftViewEnd = hftViewStart + windowSize;
}

function buildHftWindowRows() {
    var rows = [];
    var start = Math.max(0, Math.ceil(hftViewStart));
    var end = Math.min(hftRows.length, Math.floor(hftViewEnd));
    for (var index = start; index < end; index++) {
        hftRows[index].hftRenderIndex = index;
        rows.push(hftRows[index]);
    }
    return rows;
}

async function getHftData() {
    if (!hftQuery.market || !hftQuery.interval || !hftQuery.symbol) return [];
    if (!isCompleteHftDate(hftQuery.start_date) || !isCompleteHftDate(hftQuery.end_date)) return [];
    capOrderbookRange();

    var params = {
        market: hftQuery.market,
        interval: hftQuery.interval,
        symbol: hftQuery.symbol,
        adj: hftQuery.adj,
        mode: hftQuery.mode,
        start_date: hftQuery.start_date,
        end_date: hftQuery.end_date
    };
    if ((hftQuery.mode === 'cusum' || hftQuery.mode === 'volume') && Number.isFinite(hftQuery.threshold)) params.threshold = hftQuery.threshold;

    var method = hftQuery.interval === '1t' ? 'hft.tick' : 'hft.data';
    var result = await WSAPI.call(method, params);
    var rows = Array.isArray(result?.data) ? result.data : (Array.isArray(result) ? result : []);
    return normalizeHftRows(rows);
}

function downsampleRows(rows, maxPoints) {
    if (rows.length <= maxPoints) return rows;
    var step = Math.ceil(rows.length / maxPoints);
    var sampled = [];
    for (var index = 0; index < rows.length; index += step) sampled.push(rows[index]);
    if (sampled[sampled.length - 1] !== rows[rows.length - 1]) sampled.push(rows[rows.length - 1]);
    return sampled;
}

function getHftRenderMaxPoints(plotWidth, isOrderbookMode) {
    var pointGap = isOrderbookMode ? 8 : 2;
    return Math.max(2, Math.floor(plotWidth / pointGap));
}

function getHftPriceAxisStep(spread, priceHeight) {
    var tickCount = Math.max(2, Math.floor(priceHeight / 56));
    var rawStep = spread / tickCount;
    if (!Number.isFinite(rawStep) || rawStep <= 0) return spread;

    var exponent = Math.floor(Math.log10(rawStep));
    var power = Math.pow(10, exponent);
    var scaled = rawStep / power;
    var factor = scaled <= 1 ? 1 : (scaled <= 2 ? 2 : (scaled <= 5 ? 5 : 10));
    return factor * power;
}

function formatHftAxisValue(value, step) {
    var axisValue = Math.abs(value) < Math.abs(step) / 1000000 ? 0 : value;
    if (Math.abs(step) >= 1) return axisValue.toFixed(2);
    var decimals = Math.min(8, Math.ceil(Math.abs(Math.log10(Math.abs(step)))) + 1);
    return axisValue.toFixed(decimals);
}

function drawHftPriceAxis(context, axisInfo) {
    var tickStep = getHftPriceAxisStep(axisInfo.spread, axisInfo.priceHeight);
    if (!Number.isFinite(tickStep) || tickStep <= 0) return;

    var firstTick = Math.ceil(axisInfo.minValue / tickStep) * tickStep;
    var tickLimit = 0;
    context.save();
    context.font = '11px Segoe UI';
    context.textAlign = 'right';
    context.textBaseline = 'middle';
    for (var tickValue = firstTick; tickValue <= axisInfo.maxValue + tickStep * 0.5 && tickLimit < 100; tickValue += tickStep) {
        var tickY = axisInfo.priceTop + ((axisInfo.maxValue - tickValue) / axisInfo.spread) * axisInfo.priceHeight;
        tickLimit++;
        if (tickY < axisInfo.priceTop - 0.5 || tickY > axisInfo.priceTop + axisInfo.priceHeight + 0.5) continue;

        var alignedY = Math.round(tickY) + 0.5;
        context.strokeStyle = '#eaecf0';
        context.lineWidth = 1;
        context.beginPath();
        context.moveTo(axisInfo.paddingLeft, alignedY);
        context.lineTo(axisInfo.paddingLeft + axisInfo.plotWidth, alignedY);
        context.stroke();

        context.strokeStyle = '#98a2b3';
        context.beginPath();
        context.moveTo(axisInfo.paddingLeft - 5, alignedY);
        context.lineTo(axisInfo.paddingLeft, alignedY);
        context.stroke();

        context.fillStyle = '#344054';
        context.fillText(formatHftAxisValue(tickValue, tickStep), axisInfo.paddingLeft - 8, alignedY);
    }
    context.strokeStyle = '#98a2b3';
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(axisInfo.paddingLeft + 0.5, axisInfo.priceTop);
    context.lineTo(axisInfo.paddingLeft + 0.5, axisInfo.priceTop + axisInfo.priceHeight);
    context.stroke();
    context.restore();
}

function isInsideHftRect(mouseX, mouseY, rect) {
    return Boolean(rect) && mouseX >= rect.x && mouseX <= rect.x + rect.w && mouseY >= rect.y && mouseY <= rect.y + rect.h;
}

function computeQuantile(sortedValues, quantile) {
    if (!sortedValues.length) return 0;
    var q = Math.max(0, Math.min(1, Number(quantile)));
    var index = Math.floor((sortedValues.length - 1) * q);
    return sortedValues[Math.max(0, Math.min(sortedValues.length - 1, index))];
}

function getOrderbookSideTotal(row, side) {
    var total = 0;
    var levels = side === 'a' ? hftOrderbookLevels.ask : hftOrderbookLevels.bid;
    for (var index = 0; index < levels.length; index++) {
        var level = levels[index];
        var price = Number(row[side + level + '_p']);
        var volume = Number(row[side + level + '_v']);
        if (Number.isFinite(price) && price > 0 && Number.isFinite(volume) && volume > 0) total += volume;
    }
    return total;
}

function refreshHftOrderbookStats(rows) {
    var askTotals = [];
    var bidTotals = [];
    for (var i = 0; i < rows.length; i++) {
        var askTotal = getOrderbookSideTotal(rows[i], 'a');
        var bidTotal = getOrderbookSideTotal(rows[i], 'b');
        if (askTotal > 0) askTotals.push(askTotal);
        if (bidTotal > 0) bidTotals.push(bidTotal);
    }
    askTotals.sort(function(a, b) { return a - b; });
    bidTotals.sort(function(a, b) { return a - b; });

    hftOrderbookStats.askTotalQ05 = computeQuantile(askTotals, 0.05);
    hftOrderbookStats.askTotalQ15 = computeQuantile(askTotals, 0.15);
    hftOrderbookStats.askTotalQ85 = computeQuantile(askTotals, 0.85);
    hftOrderbookStats.askTotalQ95 = computeQuantile(askTotals, 0.95);
    hftOrderbookStats.bidTotalQ05 = computeQuantile(bidTotals, 0.05);
    hftOrderbookStats.bidTotalQ15 = computeQuantile(bidTotals, 0.15);
    hftOrderbookStats.bidTotalQ85 = computeQuantile(bidTotals, 0.85);
    hftOrderbookStats.bidTotalQ95 = computeQuantile(bidTotals, 0.95);
}

function refreshHftOrderbookRows(rows) {
    for (var index = 0; index < rows.length; index++) {
        var row = rows[index];
        var askSegments = markValidSegments(collectOrderbookSegments(row, 'ask'));
        var bidSegments = markValidSegments(collectOrderbookSegments(row, 'bid'));
        row.orderbook = {
            askSegments: askSegments,
            bidSegments: bidSegments,
            askRankInfo: buildSideRankMap(askSegments),
            bidRankInfo: buildSideRankMap(bidSegments),
            askTotal: getOrderbookSideTotal(row, 'a'),
            bidTotal: getOrderbookSideTotal(row, 'b')
        };
    }
}

function resetHftRenderCache() {
    hftRenderCache = { key: '', canvas: null, info: null };
}

function requestHftCanvasDraw(mouseX, mouseY) {
    hftPendingDraw = { mouseX: mouseX, mouseY: mouseY };
    if (hftDrawFrame !== null) return;
    hftDrawFrame = requestAnimationFrame(function() {
        var pending = hftPendingDraw;
        hftPendingDraw = null;
        hftDrawFrame = null;
        drawHftCanvas(pending.mouseX, pending.mouseY);
    });
}

function mixRgbColor(fromColor, toColor, ratio) {
    var value = Math.max(0, Math.min(1, ratio));
    return [
        Math.round(fromColor[0] + (toColor[0] - fromColor[0]) * value),
        Math.round(fromColor[1] + (toColor[1] - fromColor[1]) * value),
        Math.round(fromColor[2] + (toColor[2] - fromColor[2]) * value)
    ];
}

function toRgbString(color) {
    return 'rgb(' + color[0] + ', ' + color[1] + ', ' + color[2] + ')';
}

function getOrderbookBandColor(side, rank, count, sideTotal) {
    var depthRatio = count > 1 ? (count - rank) / (count - 1) : 1;
    var color = side === 'ask'
        ? mixRgbColor([255, 0, 0], [116, 0, 0], depthRatio)
        : mixRgbColor([0, 176, 80], [0, 86, 38], depthRatio);
    var q05 = side === 'ask' ? hftOrderbookStats.askTotalQ05 : hftOrderbookStats.bidTotalQ05;
    var q15 = side === 'ask' ? hftOrderbookStats.askTotalQ15 : hftOrderbookStats.bidTotalQ15;
    var q85 = side === 'ask' ? hftOrderbookStats.askTotalQ85 : hftOrderbookStats.bidTotalQ85;
    var q95 = side === 'ask' ? hftOrderbookStats.askTotalQ95 : hftOrderbookStats.bidTotalQ95;

    if (q95 > 0 && sideTotal >= q95) return mixRgbColor(color, [255, 210, 0], 0.85);
    if (q85 > 0 && sideTotal >= q85) return mixRgbColor(color, [255, 210, 0], 0.5);
    if (q05 > 0 && sideTotal <= q05) return mixRgbColor(color, [255, 255, 255], 0.85);
    if (q15 > 0 && sideTotal <= q15) return mixRgbColor(color, [255, 255, 255], 0.5);
    return color;
}

function collectOrderbookSegments(row, side) {
    var segments = [];
    if (side === 'ask') {
        for (var askIndex = hftOrderbookLevels.ask.length - 1; askIndex >= 0; askIndex--) {
            var askLevel = hftOrderbookLevels.ask[askIndex];
            segments.push({
                side: 'ask',
                level: askLevel,
                price: Number(row['a' + askLevel + '_p']),
                volume: Number(row['a' + askLevel + '_v'])
            });
        }
        return segments;
    }
    for (var bidIndex = 0; bidIndex < hftOrderbookLevels.bid.length; bidIndex++) {
        var bidLevel = hftOrderbookLevels.bid[bidIndex];
        segments.push({
            side: 'bid',
            level: bidLevel,
            price: Number(row['b' + bidLevel + '_p']),
            volume: Number(row['b' + bidLevel + '_v'])
        });
    }
    return segments;
}

function markValidSegments(segments) {
    for (var i = 0; i < segments.length; i++) {
        var item = segments[i];
        item.valid = Number.isFinite(item.price) && item.price > 0 && Number.isFinite(item.volume) && item.volume > 0;
    }
    return segments;
}

function buildSideRankMap(segments) {
    var validSegments = segments.filter(function(item) { return item.valid; }).sort(function(a, b) {
        return b.volume - a.volume;
    });
    var rankMap = {};
    for (var i = 0; i < validSegments.length; i++) {
        rankMap[validSegments[i].level] = i + 1;
    }
    return { ranks: rankMap, count: validSegments.length };
}

function getTooltipLeft(tooltip, hoverX, canvasWidth) {
    var rightLeft = hoverX + 12;
    if (rightLeft + tooltip.offsetWidth <= canvasWidth - 8) return rightLeft;
    return Math.max(8, hoverX - tooltip.offsetWidth - 12);
}

function mapOrderbookSegments(point, side, priceToY) {
    var source = side === 'ask' ? point.askSegments : point.bidSegments;
    var rankInfo = side === 'ask' ? point.askRankInfo : point.bidRankInfo;
    var total = side === 'ask' ? point.askTotal : point.bidTotal;
    var data = {};
    data[0] = {
        x: point.x,
        y: priceToY(Number(point.row.open)),
        color: side === 'ask' ? [255, 0, 0] : [0, 176, 80]
    };
    for (var i = 0; i < source.length; i++) {
        var item = source[i];
        if (!item.valid || !rankInfo.count) continue;
        var y = priceToY(item.price);
        data[item.level] = {
            x: point.x,
            y: y,
            color: getOrderbookBandColor(side, rankInfo.ranks[item.level], rankInfo.count, total),
            rect: { x: point.x, y: y, row: point.row, rowIndex: point.index, side: side, level: item.level, price: item.price, volume: item.volume }
        };
    }
    return data;
}

function drawOrderbookSurface(context, bookPoints, side, priceToY, blockWidth, bandHeight, rects) {
    var levels = side === 'ask'
        ? hftOrderbookLevels.ask.slice().sort(function(a, b) { return b - a; }).concat([0])
        : [0].concat(hftOrderbookLevels.bid);
    var sideMaps = bookPoints.map(function(point) { return mapOrderbookSegments(point, side, priceToY); });
    for (var timeIndex = 0; timeIndex < sideMaps.length - 1; timeIndex++) {
        var leftMap = sideMaps[timeIndex];
        var rightMap = sideMaps[timeIndex + 1];
        for (var levelIndex = 0; levelIndex < levels.length - 1; levelIndex++) {
            var topLevel = levels[levelIndex];
            var bottomLevel = levels[levelIndex + 1];
            var leftTop = leftMap[topLevel];
            var leftBottom = leftMap[bottomLevel];
            var rightTop = rightMap[topLevel];
            var rightBottom = rightMap[bottomLevel];
            if (!leftTop || !leftBottom || !rightTop || !rightBottom) continue;
            var gradient = context.createLinearGradient(leftTop.x, 0, rightTop.x, 0);
            gradient.addColorStop(0, toRgbString(mixRgbColor(leftTop.color, leftBottom.color, 0.5)));
            gradient.addColorStop(1, toRgbString(mixRgbColor(rightTop.color, rightBottom.color, 0.5)));
            context.fillStyle = gradient;
            context.beginPath();
            context.moveTo(leftTop.x, leftTop.y);
            context.lineTo(rightTop.x, rightTop.y);
            context.lineTo(rightBottom.x, rightBottom.y);
            context.lineTo(leftBottom.x, leftBottom.y);
            context.closePath();
            context.fill();

            var rectPoint = side === 'ask' ? leftTop.rect : leftBottom.rect;
            if (!rectPoint) continue;
            var minX = Math.min(leftTop.x, leftBottom.x, rightTop.x, rightBottom.x) - blockWidth / 2;
            var maxX = Math.max(leftTop.x, leftBottom.x, rightTop.x, rightBottom.x) + blockWidth / 2;
            var minY = Math.min(leftTop.y, leftBottom.y, rightTop.y, rightBottom.y) - bandHeight / 2;
            var maxY = Math.max(leftTop.y, leftBottom.y, rightTop.y, rightBottom.y) + bandHeight / 2;
            rects.push({
                x: minX,
                y: minY,
                w: maxX - minX,
                h: maxY - minY,
                date: rectPoint.row.date,
                open: rectPoint.row.open,
                rowIndex: rectPoint.rowIndex,
                side: rectPoint.side,
                level: rectPoint.level,
                price: rectPoint.price,
                volume: rectPoint.volume
            });
        }
    }
}

function buildOrderbookHitRows(rects) {
    var hitRows = {};
    for (var index = 0; index < rects.length; index++) {
        var rowIndex = rects[index].rowIndex;
        if (!hitRows[rowIndex]) hitRows[rowIndex] = [];
        hitRows[rowIndex].push(rects[index]);
    }
    return hitRows;
}

function findOrderbookHitRect(hitRows, hoverIndex, mouseX, mouseY) {
    for (var offset = -1; offset <= 1; offset++) {
        var rects = hitRows[hoverIndex + offset];
        if (!rects) continue;
        for (var index = 0; index < rects.length; index++) {
            var item = rects[index];
            if (mouseX >= item.x && mouseX <= item.x + item.w && mouseY >= item.y && mouseY <= item.y + item.h) return item;
        }
    }
    return null;
}

function findHftHoverIndex(pointXs, mouseX) {
    var nearestIndex = 0;
    var nearestDistance = Infinity;
    for (var index = 0; index < pointXs.length; index++) {
        var distance = Math.abs(pointXs[index] - mouseX);
        if (distance < nearestDistance) {
            nearestDistance = distance;
            nearestIndex = index;
        }
    }
    return nearestIndex;
}

function drawHftInteraction(context, canvas, tooltip, info, mouseX, mouseY) {
    if (typeof mouseX !== 'number' || mouseX < info.paddingLeft || mouseX > info.paddingLeft + info.plotWidth) {
        if (tooltip) tooltip.style.display = 'none';
        return;
    }

    if (!info.pointXs.length) {
        if (tooltip) tooltip.style.display = 'none';
        return;
    }
    var hoverIndex = findHftHoverIndex(info.pointXs, mouseX);
    var hoverX = info.pointXs[hoverIndex];
    var hoverY = info.priceTop + ((info.maxValue - info.values[hoverIndex]) / info.spread) * info.priceHeight;
    var row = info.renderRows[hoverIndex];

    context.strokeStyle = '#98a2b3';
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(hoverX, info.priceTop);
    context.lineTo(hoverX, info.volumeTop + info.volumeHeight);
    context.stroke();

    var hasMouseY = typeof mouseY === 'number' && mouseY >= info.priceTop && mouseY <= info.priceTop + info.priceHeight;
    if (hasMouseY) {
        var hoverPrice = info.maxValue - ((mouseY - info.priceTop) / Math.max(1, info.priceHeight)) * info.spread;
        context.strokeStyle = '#667085';
        context.lineWidth = 1;
        context.setLineDash([3, 3]);
        context.beginPath();
        context.moveTo(info.paddingLeft, mouseY);
        context.lineTo(info.paddingLeft + info.plotWidth, mouseY);
        context.stroke();
        context.setLineDash([]);

        context.fillStyle = '#344054';
        context.font = '11px Segoe UI';
        context.fillText(hoverPrice.toFixed(4), info.paddingLeft + 6, Math.max(info.priceTop + 12, mouseY - 4));
    }

    if (!info.isOrderbookMode) {
        context.fillStyle = '#155eef';
        context.beginPath();
        context.arc(hoverX, hoverY, 3, 0, Math.PI * 2);
        context.fill();
    }

    if (info.isOrderbookMode) drawOrderbookHoverPie(context, row, info.paddingLeft + info.plotWidth - 52, info.priceTop + info.priceHeight - 52);

    if (!tooltip) return;
    var tooltipText = formatHftDateTimeToSecond(row.date) + '\nopen: ' + Number(row.open).toFixed(4);
    if (info.isOrderbookMode) {
        var hitRect = hasMouseY ? findOrderbookHitRect(info.orderbookHitRows, hoverIndex, mouseX, mouseY) : null;
        if (hitRect) {
            tooltipText =
                formatHftDateTimeToSecond(hitRect.date) +
                '\nopen: ' + Number(hitRect.open).toFixed(4) +
                '\naction: ' + String(row.action || '') +
                '\nside: ' + hitRect.side +
                '\nlevel: ' + hitRect.level +
                '\nprice: ' + Number(hitRect.price).toFixed(4) +
                '\nvolume: ' + Number(hitRect.volume).toFixed(0);
        }
    } else {
        tooltipText += '\n' + info.volumeLabel.toLowerCase() + ': ' + Number(info.volumeSeries[hoverIndex]).toFixed(0);
    }
    tooltip.style.display = 'block';
    tooltip.innerText = tooltipText;
    tooltip.style.left = getTooltipLeft(tooltip, hoverX, info.width) + 'px';
    tooltip.style.top = (Math.max(8, hoverY - 30)) + 'px';
}

function drawOrderbookHoverPie(context, row, pieCenterX, pieCenterY) {
    var askTotal = row.orderbook.askTotal;
    var bidTotal = row.orderbook.bidTotal;
    var pieTotal = askTotal + bidTotal;
    if (pieTotal <= 0) return;

    var askRatio = askTotal / pieTotal;
    context.save();
    context.globalAlpha = 0.95;
    context.fillStyle = '#ffffff';
    context.fillRect(pieCenterX - 58, pieCenterY - 50, 116, 100);
    context.strokeStyle = '#d0d5dd';
    context.strokeRect(pieCenterX - 58, pieCenterY - 50, 116, 100);

    context.beginPath();
    context.moveTo(pieCenterX, pieCenterY);
    context.fillStyle = '#f04438';
    context.arc(pieCenterX, pieCenterY, 36, -Math.PI / 2, -Math.PI / 2 + askRatio * Math.PI * 2);
    context.closePath();
    context.fill();

    context.beginPath();
    context.moveTo(pieCenterX, pieCenterY);
    context.fillStyle = '#12b76a';
    context.arc(pieCenterX, pieCenterY, 36, -Math.PI / 2 + askRatio * Math.PI * 2, -Math.PI / 2 + Math.PI * 2);
    context.closePath();
    context.fill();

    context.beginPath();
    context.fillStyle = '#ffffff';
    context.arc(pieCenterX, pieCenterY, 18, 0, Math.PI * 2);
    context.fill();

    context.fillStyle = '#344054';
    context.font = '10px Segoe UI';
    context.fillText('ASK ' + Math.round(askRatio * 100) + '%', pieCenterX - 50, pieCenterY + 48);
    context.fillText('BID ' + Math.round((1 - askRatio) * 100) + '%', pieCenterX + 2, pieCenterY + 48);
    context.restore();
}

function drawHftCanvas(mouseX, mouseY) {
    var canvas = document.getElementById('hft-canvas');
    var tooltip = document.getElementById('hft-tooltip');
    if (!canvas) return;

    var rect = canvas.getBoundingClientRect();
    var width = Math.max(1, Math.floor(rect.width));
    var height = Math.max(1, Math.floor(rect.height));
    canvas.width = width;
    canvas.height = height;

    var context = canvas.getContext('2d');
    context.clearRect(0, 0, width, height);
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, width, height);

    if (!hftRows.length) {
        context.fillStyle = '#667085';
        context.font = '14px Segoe UI';
        context.fillText('无数据', 24, 40);
        return;
    }

    ensureHftWindowValid();
    var renderKey = [
        hftQuery.market,
        hftQuery.interval,
        hftQuery.symbol,
        hftQuery.mode,
        hftViewStart,
        hftViewEnd,
        hftRows.length,
        hftPriceViewMin,
        hftPriceViewMax,
        width,
        height
    ].join('|');
    if (hftRenderCache.key === renderKey && hftRenderCache.canvas && hftRenderCache.info) {
        context.drawImage(hftRenderCache.canvas, 0, 0);
        hftNavigatorRect = hftRenderCache.info.navigatorRect;
        canvas._navigatorSelection = hftRenderCache.info.navigatorSelection;
        drawHftInteraction(context, canvas, tooltip, hftRenderCache.info, mouseX, mouseY);
        return;
    }

    var paddingLeft = 66;
    var paddingTop = 18;
    var paddingRight = 18;
    var paddingBottom = 28;
    var panelGap = 10;
    var volumePanelHeight = Math.max(56, Math.floor((height - paddingTop - paddingBottom) * 0.22));
    var pricePanelHeight = Math.max(60, height - paddingTop - paddingBottom - volumePanelHeight - panelGap);
    var plotWidth = Math.max(1, width - paddingLeft - paddingRight);
    var isOrderbookMode = hftQuery.mode === 'orderbook';
    var windowRows = buildHftWindowRows();
    var renderRows = downsampleRows(windowRows, getHftRenderMaxPoints(plotWidth, isOrderbookMode));
    if (!renderRows.length) {
        context.fillStyle = '#667085';
        context.font = '14px Segoe UI';
        context.fillText('无数据', 24, 40);
        return;
    }
    var pointCount = Math.max(1, hftViewEnd - hftViewStart - 1);
    var pointXs = renderRows.map(function(item) {
        return paddingLeft + (plotWidth * (item.hftRenderIndex - hftViewStart) / pointCount);
    });
    var values = renderRows.map(function(item) { return item.open; });
    var minValue = Math.min.apply(null, values);
    var maxValue = Math.max.apply(null, values);
    if (hftQuery.mode === 'orderbook') {
        for (var rangeIndex = 0; rangeIndex < renderRows.length; rangeIndex++) {
            for (var askRangeIndex = 0; askRangeIndex < hftOrderbookLevels.ask.length; askRangeIndex++) {
                var askRangePrice = Number(renderRows[rangeIndex]['a' + hftOrderbookLevels.ask[askRangeIndex] + '_p']);
                if (Number.isFinite(askRangePrice) && askRangePrice > 0) {
                    minValue = Math.min(minValue, askRangePrice);
                    maxValue = Math.max(maxValue, askRangePrice);
                }
            }
            for (var bidRangeIndex = 0; bidRangeIndex < hftOrderbookLevels.bid.length; bidRangeIndex++) {
                var bidRangePrice = Number(renderRows[rangeIndex]['b' + hftOrderbookLevels.bid[bidRangeIndex] + '_p']);
                if (Number.isFinite(bidRangePrice) && bidRangePrice > 0) {
                    minValue = Math.min(minValue, bidRangePrice);
                    maxValue = Math.max(maxValue, bidRangePrice);
                }
            }
        }
    }
    ensureHftPriceWindowValid(minValue, maxValue);
    minValue = hftPriceViewMin;
    maxValue = hftPriceViewMax;
    var spread = maxValue - minValue || 1;
    var priceTop = paddingTop;
    var priceHeight = pricePanelHeight;
    var volumeTop = priceTop + priceHeight + panelGap;
    var volumeHeight = volumePanelHeight;
    var actionBandHeight = isOrderbookMode ? 14 : 0;
    var actionBandTop = priceTop + 2;
    var priceAxisRect = { x: 0, y: priceTop, w: paddingLeft, h: priceHeight };

    context.strokeStyle = '#d0d5dd';
    context.lineWidth = 1;
    context.strokeRect(paddingLeft, priceTop, plotWidth, priceHeight);
    context.strokeRect(paddingLeft, volumeTop, plotWidth, volumeHeight);
    drawHftPriceAxis(context, {
        paddingLeft: paddingLeft,
        plotWidth: plotWidth,
        priceTop: priceTop,
        priceHeight: priceHeight,
        minValue: minValue,
        maxValue: maxValue,
        spread: spread
    });

    var orderbookHitRows = {};
    if (!isOrderbookMode) {
        context.strokeStyle = '#155eef';
        context.lineWidth = 1.5;
        context.beginPath();
        for (var index = 0; index < values.length; index++) {
            var x = pointXs[index];
            var y = priceTop + ((maxValue - values[index]) / spread) * priceHeight;
            if (index === 0) context.moveTo(x, y);
            else context.lineTo(x, y);
        }
        context.stroke();
    } else {
        var blockSlotWidth = plotWidth / pointCount;
        var blockWidth = Math.max(6, Math.ceil(blockSlotWidth));
        var rects = [];
        var centers = [];
        var validPriceCount = 0;
        for (var priceCountIndex = 0; priceCountIndex < renderRows.length; priceCountIndex++) {
            for (var askPriceCountIndex = 0; askPriceCountIndex < hftOrderbookLevels.ask.length; askPriceCountIndex++) {
                if (Number(renderRows[priceCountIndex]['a' + hftOrderbookLevels.ask[askPriceCountIndex] + '_p']) > 0) validPriceCount++;
            }
            for (var bidPriceCountIndex = 0; bidPriceCountIndex < hftOrderbookLevels.bid.length; bidPriceCountIndex++) {
                if (Number(renderRows[priceCountIndex]['b' + hftOrderbookLevels.bid[bidPriceCountIndex] + '_p']) > 0) validPriceCount++;
            }
        }
        var priceBandHeight = Math.max(4, Math.min(18, Math.ceil(priceHeight / Math.max(12, Math.sqrt(validPriceCount)))));
        var priceToY = function(price) {
            return priceTop + ((maxValue - price) / spread) * priceHeight;
        };
        var bookPoints = [];

        for (var bookIndex = 0; bookIndex < renderRows.length; bookIndex++) {
            var row = renderRows[bookIndex];
            var centerLineY = priceToY(Number(row.open));
            var bookX = pointXs[bookIndex];
            centers.push({
                x: bookX,
                y: centerLineY
            });
            bookPoints.push({
                row: row,
                index: bookIndex,
                x: bookX,
                askSegments: row.orderbook.askSegments,
                bidSegments: row.orderbook.bidSegments,
                askRankInfo: row.orderbook.askRankInfo,
                bidRankInfo: row.orderbook.bidRankInfo,
                askTotal: row.orderbook.askTotal,
                bidTotal: row.orderbook.bidTotal
            });
        }
        drawOrderbookSurface(context, bookPoints, 'ask', priceToY, blockWidth, priceBandHeight, rects);
        drawOrderbookSurface(context, bookPoints, 'bid', priceToY, blockWidth, priceBandHeight, rects);
        context.strokeStyle = '#98a2b3';
        context.lineWidth = 1;
        context.setLineDash([4, 3]);
        context.beginPath();
        for (var centerIndex = 0; centerIndex < centers.length; centerIndex++) {
            var centerPoint = centers[centerIndex];
            if (centerIndex === 0) context.moveTo(centerPoint.x, centerPoint.y);
            else context.lineTo(centerPoint.x, centerPoint.y);
        }
        context.stroke();
        context.setLineDash([]);
        orderbookHitRows = buildOrderbookHitRows(rects);
    }

    if (isOrderbookMode) {
        for (var actionIndex = 0; actionIndex < renderRows.length; actionIndex++) {
            var actionRow = renderRows[actionIndex];
            var action = String(actionRow.action || '').toLowerCase();
            var actionX = pointXs[actionIndex];
            var actionNextX = actionIndex + 1 < pointXs.length ? pointXs[actionIndex + 1] : actionX + plotWidth / pointCount;
            var actionWidth = Math.max(1, Math.ceil(actionNextX - actionX));
            context.fillStyle = action === 'buy' ? '#12b76a' : (action === 'sell' ? '#f04438' : '#667085');
            context.fillRect(Math.floor(actionX), actionBandTop, actionWidth, actionBandHeight);
        }
    }

    var isBarMode = hftQuery.mode === 'cusum' || hftQuery.mode === 'volume';
    var volumeSeries = renderRows.map(function(item) {
        if (isBarMode && Number.isFinite(item.ticks) && item.ticks > 0) return item.ticks;
        return item.volume;
    });
    var maxVolume = Math.max.apply(null, volumeSeries.concat([1]));
    var volumeLabel = (isBarMode && renderRows.some(function(item) { return Number.isFinite(item.ticks) && item.ticks > 0; })) ? 'Ticks' : 'Volume';

    context.fillStyle = '#667085';
    context.font = '11px Segoe UI';
    context.fillText(volumeLabel, 8, volumeTop + 10);

    var barStep = plotWidth / Math.max(1, volumeSeries.length - 1);
    var barWidth = Math.max(1, Math.min(8, Math.floor(barStep * 0.75)));
    context.fillStyle = '#12b76a';
    for (var barIndex = 0; barIndex < volumeSeries.length; barIndex++) {
        var barX = pointXs[barIndex];
        var barHeight = (Math.max(0, volumeSeries[barIndex]) / maxVolume) * (volumeHeight - 4);
        var barTop = volumeTop + volumeHeight - barHeight;
        context.fillRect(barX - Math.floor(barWidth / 2), barTop, barWidth, barHeight);
    }
    var navPadding = 8;
    var navHeight = Math.max(22, Math.floor(volumeHeight * 0.55));
    var navTop = volumeTop + volumeHeight - navHeight - 2;
    var navLeft = paddingLeft + navPadding;
    var navWidth = Math.max(20, plotWidth - navPadding * 2);
    var navRect = { x: navLeft, y: navTop, w: navWidth, h: navHeight };
    hftNavigatorRect = navRect;
    context.fillStyle = 'rgba(52, 64, 84, 0.08)';
    context.fillRect(navRect.x, navRect.y, navRect.w, navRect.h);
    context.strokeStyle = 'rgba(52, 64, 84, 0.25)';
    context.strokeRect(navRect.x, navRect.y, navRect.w, navRect.h);

    var navBars = downsampleRows(hftRows, Math.max(150, Math.floor(navRect.w)));
    var navValues = navBars.map(function(item) { return Number(item.volume); });
    var navMax = Math.max.apply(null, navValues.concat([1]));
    context.fillStyle = 'rgba(18, 183, 106, 0.45)';
    for (var navIndex = 0; navIndex < navBars.length; navIndex++) {
        var navX = navRect.x + (navRect.w * navIndex / Math.max(1, navBars.length - 1));
        var navBarH = (Math.max(0, navValues[navIndex]) / navMax) * (navRect.h - 3);
        context.fillRect(Math.floor(navX), navRect.y + navRect.h - navBarH, 1, navBarH);
    }
    var totalRows = hftRows.length;
    var viewStartRatio = totalRows > 1 ? hftViewStart / (totalRows - 1) : 0;
    var viewEndRatio = totalRows > 1 ? (hftViewEnd - 1) / (totalRows - 1) : 1;
    var selX = navRect.x + navRect.w * viewStartRatio;
    var selW = Math.max(8, navRect.w * Math.max(0.01, viewEndRatio - viewStartRatio));
    if (selX + selW > navRect.x + navRect.w) selW = navRect.x + navRect.w - selX;
    canvas._navigatorSelection = { x: selX, y: navRect.y, w: selW, h: navRect.h };
    context.fillStyle = 'rgba(21, 94, 239, 0.20)';
    context.fillRect(selX, navRect.y, selW, navRect.h);
    context.strokeStyle = 'rgba(21, 94, 239, 0.8)';
    context.strokeRect(selX, navRect.y, selW, navRect.h);

    var staticCanvas = document.createElement('canvas');
    staticCanvas.width = width;
    staticCanvas.height = height;
    staticCanvas.getContext('2d').drawImage(canvas, 0, 0);
    hftRenderCache.key = renderKey;
    hftRenderCache.canvas = staticCanvas;
    hftRenderCache.info = {
        width: width,
        paddingLeft: paddingLeft,
        plotWidth: plotWidth,
        priceTop: priceTop,
        priceHeight: priceHeight,
        volumeTop: volumeTop,
        volumeHeight: volumeHeight,
        values: values,
        pointCount: pointCount,
        pointXs: pointXs,
        renderRows: renderRows,
        spread: spread,
        minValue: minValue,
        maxValue: maxValue,
        isOrderbookMode: isOrderbookMode,
        volumeSeries: volumeSeries,
        volumeLabel: volumeLabel,
        orderbookHitRows: orderbookHitRows,
        navigatorRect: navRect,
        navigatorSelection: canvas._navigatorSelection,
        priceAxisRect: priceAxisRect
    };
    drawHftInteraction(context, canvas, tooltip, hftRenderCache.info, mouseX, mouseY);
}

function bindHftCanvasResize() {
    var canvas = document.getElementById('hft-canvas');
    if (!canvas) return;
    if (hftCanvasObserver) hftCanvasObserver.disconnect();
    hftCanvasObserver = new ResizeObserver(function() {
        drawHftCanvas();
    });
    hftCanvasObserver.observe(canvas);
}

function init_hft() {
    hftActiveToken++;
    bindHftCanvasResize();
    populateHftMarkets();

    var rangeSelect = document.getElementById('hft-range');
    if (rangeSelect) {
        rangeSelect.value = '1m';
        applyHftPresetRange('1m');
    }

    var container = document.getElementById('hft-symbol-grid-container');
    if (container) {
        container.addEventListener('scroll', function() {
            if (container.scrollTop + container.clientHeight >= container.scrollHeight - 20) loadMoreHftSymbols();
        });
    }

    drawHftCanvas();
    bindHftCanvasPointer();
}

function destroy_hft() {
    hftActiveToken++;
    hftDragState = null;
    hftNavigatorDrag = null;
    hftPriceAxisDrag = null;
    if (hftDrawFrame !== null) {
        cancelAnimationFrame(hftDrawFrame);
        hftDrawFrame = null;
        hftPendingDraw = null;
    }
    if (hftCanvasObserver) {
        hftCanvasObserver.disconnect();
        hftCanvasObserver = null;
    }
}

function zoomHftTimeWindow(mouseX, info, zoomFactor) {
    if (!info) return;
    ensureHftWindowValid();
    var currentSize = hftViewEnd - hftViewStart;
    var minSize = Math.min(2, hftRows.length);
    var nextSize = currentSize * zoomFactor;
    nextSize = Math.max(minSize, Math.min(hftRows.length, nextSize));
    var anchorRatio = Math.max(0, Math.min(1, (mouseX - info.paddingLeft) / Math.max(1, info.plotWidth)));
    var anchorIndex = hftViewStart + currentSize * anchorRatio;
    hftViewStart = anchorIndex - nextSize * anchorRatio;
    hftViewEnd = hftViewStart + nextSize;
    ensureHftWindowValid();
}

function zoomHftPriceAxis(mouseY, info, zoomFactor) {
    if (!info || mouseY < info.priceTop || mouseY > info.priceTop + info.priceHeight) return;
    var currentMin = info.minValue;
    var currentMax = info.maxValue;
    var currentSpread = currentMax - currentMin;
    if (currentSpread <= 0) return;
    var anchorRatio = (mouseY - info.priceTop) / Math.max(1, info.priceHeight);
    var anchorPrice = currentMax - anchorRatio * currentSpread;
    var nextSpread = currentSpread * zoomFactor;
    hftPriceViewMin = anchorPrice - (1 - anchorRatio) * nextSpread;
    hftPriceViewMax = anchorPrice + anchorRatio * nextSpread;
}

function startHftPriceAxisDrag(event, mouseY, info) {
    var currentSpread = info.maxValue - info.minValue;
    if (currentSpread <= 0) return false;
    var anchorRatio = (mouseY - info.priceTop) / Math.max(1, info.priceHeight);
    hftPriceAxisDrag = {
        y: event.clientY,
        anchorRatio: anchorRatio,
        anchorPrice: info.maxValue - anchorRatio * currentSpread,
        spread: currentSpread,
        priceHeight: info.priceHeight
    };
    return true;
}

function updateHftPriceAxisDrag(event, canvas) {
    var rect = canvas.getBoundingClientRect();
    var deltaY = event.clientY - hftPriceAxisDrag.y;
    var scaleRatio = Math.exp((deltaY / Math.max(1, hftPriceAxisDrag.priceHeight)) * 2);
    var nextSpread = hftPriceAxisDrag.spread * scaleRatio;
    if (!Number.isFinite(nextSpread) || nextSpread <= 0) return;
    hftPriceViewMin = hftPriceAxisDrag.anchorPrice - (1 - hftPriceAxisDrag.anchorRatio) * nextSpread;
    hftPriceViewMax = hftPriceAxisDrag.anchorPrice + hftPriceAxisDrag.anchorRatio * nextSpread;
    resetHftRenderCache();
    requestHftCanvasDraw(event.clientX - rect.left, event.clientY - rect.top);
}

function bindHftCanvasPointer() {
    var canvas = document.getElementById('hft-canvas');
    var tooltip = document.getElementById('hft-tooltip');
    if (!canvas) return;

    canvas.onwheel = function(event) {
        if (!hftRows.length) return;
        event.preventDefault();

        var rect = canvas.getBoundingClientRect();
        var mouseX = Math.max(0, Math.min(rect.width, event.clientX - rect.left));
        var mouseY = Math.max(0, Math.min(rect.height, event.clientY - rect.top));
        var zoomFactor = event.deltaY < 0 ? 0.85 : 1.15;
        var info = hftRenderCache.info;
        if (!info) return;
        if (isInsideHftRect(mouseX, mouseY, info.priceAxisRect)) {
            zoomHftPriceAxis(mouseY, info, zoomFactor);
        } else {
            zoomHftTimeWindow(mouseX, info, zoomFactor);
        }
        resetHftRenderCache();
        drawHftCanvas(mouseX, mouseY);
    };

    canvas.onmousedown = function(event) {
        if (!hftRows.length) return;
        ensureHftWindowValid();
        var rect = canvas.getBoundingClientRect();
        var mouseX = event.clientX - rect.left;
        var mouseY = event.clientY - rect.top;
        var info = hftRenderCache.info;
        if (!info) return;
        if (isInsideHftRect(mouseX, mouseY, info.priceAxisRect)) {
            if (startHftPriceAxisDrag(event, mouseY, info)) {
                canvas.style.cursor = 'ns-resize';
                event.preventDefault();
                return;
            }
        }
        var nav = hftNavigatorRect;
        var navSel = canvas._navigatorSelection;
        if (nav && mouseX >= nav.x && mouseX <= nav.x + nav.w && mouseY >= nav.y && mouseY <= nav.y + nav.h) {
            if (navSel && mouseX >= navSel.x && mouseX <= navSel.x + navSel.w && mouseY >= navSel.y && mouseY <= navSel.y + navSel.h) {
                hftNavigatorDrag = {
                    offsetX: mouseX - navSel.x
                };
            } else {
                var ratio = (mouseX - nav.x) / Math.max(1, nav.w);
                var total = hftRows.length;
                var winSize = Math.max(2, hftViewEnd - hftViewStart);
                var anchor = Math.round(ratio * (total - 1));
                var nextStart = anchor - Math.floor(winSize / 2);
                nextStart = Math.max(0, Math.min(total - winSize, nextStart));
                hftViewStart = nextStart;
                hftViewEnd = nextStart + winSize;
                drawHftCanvas(mouseX, mouseY);
            }
            return;
        }
        hftDragState = {
            x: event.clientX,
            y: event.clientY,
            start: hftViewStart,
            end: hftViewEnd,
            minValue: info.minValue,
            maxValue: info.maxValue,
            priceTop: info.priceTop,
            priceHeight: info.priceHeight
        };
        canvas.style.cursor = 'grabbing';
    };

    window.addEventListener('mouseup', function() {
        hftDragState = null;
        hftNavigatorDrag = null;
        hftPriceAxisDrag = null;
        if (canvas) canvas.style.cursor = 'default';
    });

    window.addEventListener('mousemove', function(event) {
        if (hftPriceAxisDrag && hftRows.length) {
            updateHftPriceAxisDrag(event, canvas);
            return;
        }
        if (hftNavigatorDrag && hftRows.length && hftNavigatorRect && canvas._navigatorSelection) {
            var rect = canvas.getBoundingClientRect();
            var mouseX = event.clientX - rect.left;
            var nav = hftNavigatorRect;
            var navSel = canvas._navigatorSelection;
            var targetX = mouseX - hftNavigatorDrag.offsetX;
            var ratio = (targetX - nav.x) / Math.max(1, nav.w - navSel.w);
            var total = hftRows.length;
            var winSize = Math.max(2, hftViewEnd - hftViewStart);
            var maxStart = Math.max(0, total - winSize);
            hftViewStart = ratio * maxStart;
            hftViewEnd = hftViewStart + winSize;
            requestHftCanvasDraw(mouseX, event.clientY - rect.top);
            return;
        }
        if (!hftDragState || !hftRows.length) return;
        var windowSize = hftDragState.end - hftDragState.start;
        var rect = canvas.getBoundingClientRect();
        var deltaX = event.clientX - hftDragState.x;
        var deltaY = event.clientY - hftDragState.y;
        var moveCount = (deltaX / Math.max(1, rect.width)) * windowSize;
        var nextStart = hftDragState.start - moveCount;
        var nextEnd = hftDragState.end - moveCount;
        hftViewStart = nextStart;
        hftViewEnd = nextEnd;
        if (Number.isFinite(hftDragState.minValue) && Number.isFinite(hftDragState.maxValue)) {
            var priceSpread = hftDragState.maxValue - hftDragState.minValue;
            var priceOffset = (deltaY / Math.max(1, hftDragState.priceHeight)) * priceSpread;
            hftPriceViewMin = hftDragState.minValue + priceOffset;
            hftPriceViewMax = hftDragState.maxValue + priceOffset;
        }
        resetHftRenderCache();
        requestHftCanvasDraw(event.clientX - rect.left, event.clientY - rect.top);
    });

    canvas.onmousemove = function(event) {
        var rect = canvas.getBoundingClientRect();
        var mouseX = event.clientX - rect.left;
        var mouseY = event.clientY - rect.top;
        if (!hftDragState && !hftNavigatorDrag && !hftPriceAxisDrag) {
            var info = hftRenderCache.info;
            canvas.style.cursor = info && isInsideHftRect(mouseX, mouseY, info.priceAxisRect) ? 'ns-resize' : 'default';
        }
        requestHftCanvasDraw(mouseX, mouseY);
    };
    canvas.onmouseleave = function() {
        if (tooltip) tooltip.style.display = 'none';
        hftNavigatorDrag = null;
        if (!hftDragState && !hftPriceAxisDrag) canvas.style.cursor = 'default';
        drawHftCanvas();
    };
}

async function populateHftMarkets() {
    var data = await WSAPI.call('tasks.get');
    var markets = Object.keys(data).filter(function(item) { return item && item !== 'System'; });
    var select = document.getElementById('hft-market');
    if (!select) return;

    select.innerHTML = '<option value="">选择市场</option>';
    markets.forEach(function(item) {
        var option = document.createElement('option');
        option.value = item;
        option.innerText = item.toUpperCase();
        select.appendChild(option);
    });
}

async function onHftMarketChange() {
    var token = ++hftActiveToken;
    var market = document.getElementById('hft-market').value;
    var intervalSelect = document.getElementById('hft-interval');
    var symbolInput = document.getElementById('hft-symbol-manual');
    var loadButton = document.getElementById('btn-load-hft');
    var symbolList = document.getElementById('hft-symbol-list');

    if (intervalSelect) {
        intervalSelect.innerHTML = '<option value="">加载中...</option>';
        intervalSelect.disabled = true;
    }
    if (symbolInput) {
        symbolInput.disabled = true;
        symbolInput.value = '';
    }
    if (loadButton) loadButton.disabled = true;
    if (symbolList) symbolList.innerHTML = '';

    hftOverviewData = [];
    hftRenderedCount = 0;
    var container = document.getElementById('hft-symbol-grid-container');
    if (container) container.innerHTML = '';
    if (!market) return;

    var tables = await WSAPI.call('kline.tables', { market: market });
    if (token !== hftActiveToken) return;
    if (!Array.isArray(tables)) return;

    if (intervalSelect) {
        intervalSelect.innerHTML = '';
        if (tables.length === 0) {
            intervalSelect.innerHTML = '<option value="">该市场无K线数据</option>';
            return;
        }
        tables.forEach(function(item) {
            var option = document.createElement('option');
            option.value = item.interval;
            option.innerText = item.interval.toUpperCase();
            intervalSelect.appendChild(option);
        });
        intervalSelect.disabled = false;
    }

    if (symbolInput) symbolInput.disabled = false;
    if (loadButton) loadButton.disabled = false;

    var symbols = await WSAPI.call('kline.symbols', { market: market });
    if (token !== hftActiveToken) return;
    if (symbolList && Array.isArray(symbols)) {
        symbols.forEach(function(item) {
            var option = document.createElement('option');
            option.value = item;
            symbolList.appendChild(option);
        });
    }

    setHftModeOptions();
    await loadHftOverview();
}

async function onHftIntervalChange() {
    hftActiveToken++;
    setHftModeOptions();
    await loadHftOverview();
}

async function loadHftOverview() {
    var token = hftActiveToken;
    var market = document.getElementById('hft-market').value;
    var interval = document.getElementById('hft-interval').value;
    if (!market || !interval) return;

    hftOverviewData = [];
    hftRenderedCount = 0;
    var container = document.getElementById('hft-symbol-grid-container');
    if (container) container.innerHTML = '加载中...';

    hftOverviewData = await WSAPI.call('hft.overview', { market: market });
    if (token !== hftActiveToken || !container) return;

    if (!hftOverviewData.length) {
        container.innerHTML = '<div style="color:#667085">无数据</div>';
        return;
    }

    sortHftSymbols(null);
}

function sortHftSymbols(buttonElement) {
    if (buttonElement) {
        var buttons = document.querySelectorAll('#view-hft .symbol-list-controls .btn-xs');
        buttons.forEach(function(item) { item.classList.remove('active'); });
        buttonElement.classList.add('active');
    }

    hftOverviewData.sort(function(a, b) {
        return (a.symbol || '').localeCompare(b.symbol || '');
    });

    hftRenderedCount = 0;
    var container = document.getElementById('hft-symbol-grid-container');
    if (container) container.innerHTML = '';
    loadMoreHftSymbols();
}

function loadMoreHftSymbols() {
    var container = document.getElementById('hft-symbol-grid-container');
    if (!container) return;

    var fragment = document.createDocumentFragment();
    var start = hftRenderedCount;
    var end = Math.min(start + 100, hftOverviewData.length);
    if (start >= end) return;

    for (var index = start; index < end; index++) {
        var item = hftOverviewData[index];
        var card = document.createElement('div');
        card.className = 'symbol-card';
        if (item.symbol === hftCurrentSymbol) card.classList.add('selected');
        card.innerHTML = '<div class="name" title="' + (item.short_name || '') + '">' + (item.short_name || '-') + '</div><div class="code">' + (item.symbol || '') + '</div>';
        card.onclick = function(selectedItem, selectedCard) {
            return function() {
                hftCurrentSymbol = selectedItem.symbol;
                container.querySelectorAll('.symbol-card').forEach(function(entry) { entry.classList.remove('selected'); });
                selectedCard.classList.add('selected');
                var input = document.getElementById('hft-symbol-manual');
                if (input) input.value = selectedItem.symbol;
                loadHft(selectedItem.symbol);
            };
        }(item, card);
        fragment.appendChild(card);
    }

    container.appendChild(fragment);
    hftRenderedCount = end;
}

function loadHftFromInput() {
    var input = document.getElementById('hft-symbol-manual');
    var symbol = input ? input.value.trim() : '';
    if (!symbol) return;
    hftCurrentSymbol = symbol;
    loadHft(symbol);
}

async function loadHft(symbol, fromPreset) {
    updateHftQuery(symbol, fromPreset);
    if (!hasCompleteHftDateRange()) return;
    if (!hftQuery.market || !hftQuery.interval || !hftQuery.symbol) return;
    hftCurrentSymbol = hftQuery.symbol;

    var token = ++hftActiveToken;
    var rows = await getHftData();
    if (token !== hftActiveToken) return;
    hftRows = rows;
    refreshHftOrderbookStats(hftRows);
    refreshHftOrderbookRows(hftRows);
    resetHftViewWindow();
    resetHftRenderCache();
    drawHftCanvas();
}
