var klineChart = null;
var allOverviewData = [];
var renderedCount = 0;
var currentSymbol = '';
var currentKlineSortKey = 'symbol';
var currentKlineSortDirection = 'asc';
var activeLoadToken = 0;
var klineResizeObserver = null;

var klineQuery = {
    market: '',
    symbol: '',
    interval: '',
    adj: 'none',
    start_date: null,
    end_date: null
};

function toYmd(value) {
    var year = value.getFullYear();
    var month = String(value.getMonth() + 1).padStart(2, '0');
    var day = String(value.getDate()).padStart(2, '0');
    return year + '-' + month + '-' + day;
}

function isCompleteKlineDate(value) {
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

function hasCompleteKlineDateRange() {
    var startInput = document.getElementById('kline-start-date');
    var endInput = document.getElementById('kline-end-date');
    if (startInput?.validity?.badInput || endInput?.validity?.badInput) return false;
    return isCompleteKlineDate(startInput?.value) && isCompleteKlineDate(endInput?.value);
}

function applyPresetRange(preset) {
    var startInput = document.getElementById('kline-start-date');
    var endInput = document.getElementById('kline-end-date');
    if (!startInput || !endInput) return;

    var end = new Date();
    var start = null;
    if (preset === '1w') start = new Date(end.getFullYear(), end.getMonth(), end.getDate() - 7);
    if (preset === '1m') start = new Date(end.getFullYear(), end.getMonth(), end.getDate() - 30);
    if (preset === '1y') start = new Date(end.getFullYear() - 1, end.getMonth(), end.getDate());

    startInput.value = start ? toYmd(start) : '';
    endInput.value = toYmd(end);
}

function parseIntervalToPeriod(interval) {
    var text = String(interval || '').toLowerCase();
    var match = text.match(/^(\d+)([a-z]+)$/);
    if (!match) return { type: 'day', span: 1 };

    var span = Number(match[1]);
    var unit = match[2];
    if (unit === 'm' || unit === 'min' || unit === 'minute') return { type: 'minute', span: span };
    if (unit === 'h' || unit === 'hour') return { type: 'hour', span: span };
    return { type: 'day', span: span };
}

function mapRowsToKline(rows) {
    return rows.map(function(item) {
        var dateText = String(item.date || '').trim().replace(/\./g, '-').replace(' ', 'T');
        var timestamp = Date.parse(dateText);
        return {
            timestamp: timestamp,
            open: Number(item.open),
            high: Number(item.high),
            low: Number(item.low),
            close: Number(item.close),
            volume: Number(item.volume || 0)
        };
    }).filter(function(item) {
        return Number.isFinite(item.timestamp) && Number.isFinite(item.open) && Number.isFinite(item.high) && Number.isFinite(item.low) && Number.isFinite(item.close);
    });
}

function updateKlineQuery(symbol, fromPreset) {
    var rangeSelect = document.getElementById('kline-range');
    if (fromPreset === true && rangeSelect) applyPresetRange(rangeSelect.value || '1m');

    klineQuery.market = document.getElementById('kline-market')?.value || '';
    klineQuery.interval = document.getElementById('kline-interval')?.value || '';
    klineQuery.symbol = symbol || currentSymbol || (document.getElementById('kline-symbol-manual')?.value || '').trim();
    klineQuery.adj = document.getElementById('kline-adj')?.value || 'none';
    klineQuery.start_date = document.getElementById('kline-start-date')?.value || null;
    klineQuery.end_date = document.getElementById('kline-end-date')?.value || null;
}

async function getBarsFromServer() {
    if (!klineQuery.market || !klineQuery.interval || !klineQuery.symbol) return [];
    if (!isCompleteKlineDate(klineQuery.start_date) || !isCompleteKlineDate(klineQuery.end_date)) return [];
    var params = {
        market: klineQuery.market,
        interval: klineQuery.interval,
        symbol: klineQuery.symbol,
        adj: klineQuery.adj,
        start_date: klineQuery.start_date,
        end_date: klineQuery.end_date
    };
    var result = await WSAPI.call('kline.data', params);
    var rows = Array.isArray(result?.data) ? result.data : (Array.isArray(result) ? result : []);
    return mapRowsToKline(rows).sort(function(a, b) { return a.timestamp - b.timestamp; });
}

function bindKlineResize() {
    var chartDom = document.getElementById('kline-chart-area');
    if (!chartDom || !klineChart) return;
    if (klineResizeObserver) klineResizeObserver.disconnect();
    klineResizeObserver = new ResizeObserver(function() {
        if (klineChart && typeof klineChart.resize === 'function') klineChart.resize();
    });
    klineResizeObserver.observe(chartDom);
}

function init_kline() {
    activeLoadToken++;
    var chartDom = document.getElementById('kline-chart-area');
    if (!chartDom || !window.klinecharts) return;

    if (klineChart && typeof klineChart.dispose === 'function') klineChart.dispose();
    klineChart = klinecharts.init('kline-chart-area');
    klineChart.createIndicator('VOL', false);
    bindKlineResize();

    klineChart.setDataLoader({
        getBars: async function(loaderParams) {
            var token = activeLoadToken;
            var list = await getBarsFromServer();
            if (token !== activeLoadToken) return;
            loaderParams.callback(list, false);
        }
    });

    populateMarkets();

    var rangeSelect = document.getElementById('kline-range');
    if (rangeSelect) {
        rangeSelect.value = '1m';
        applyPresetRange('1m');
    }

    var container = document.getElementById('symbol-grid-container');
    if (container) {
        container.addEventListener('scroll', function() {
            if (container.scrollTop + container.clientHeight >= container.scrollHeight - 20) loadMoreSymbols();
        });
    }
}

function destroy_kline() {
    activeLoadToken++;
    if (klineResizeObserver) {
        klineResizeObserver.disconnect();
        klineResizeObserver = null;
    }
    if (klineChart && typeof klineChart.dispose === 'function') klineChart.dispose();
    klineChart = null;
}

async function populateMarkets() {
    var data = await WSAPI.call('tasks.get');
    var markets = Object.keys(data).filter(function(item) { return item && item !== 'System'; });
    var select = document.getElementById('kline-market');
    if (!select) return;
    select.innerHTML = '<option value="">选择市场</option>';
    markets.forEach(function(item) {
        var option = document.createElement('option');
        option.value = item;
        option.innerText = item.toUpperCase();
        select.appendChild(option);
    });
}

async function onMarketChange() {
    var token = ++activeLoadToken;
    var market = document.getElementById('kline-market').value;
    var intervalSelect = document.getElementById('kline-interval');
    var symbolInput = document.getElementById('kline-symbol-manual');
    var loadButton = document.getElementById('btn-load-kline');
    var symbolList = document.getElementById('symbol-list');

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

    allOverviewData = [];
    renderedCount = 0;
    var container = document.getElementById('symbol-grid-container');
    if (container) container.innerHTML = '';
    if (!market) return;

    var tables = await WSAPI.call('kline.tables', { market: market });
    if (token !== activeLoadToken) return;

    if (!Array.isArray(tables)) {
        if (intervalSelect) intervalSelect.innerHTML = '<option value="">数据格式错误</option>';
        return;
    }

    if (intervalSelect) {
        intervalSelect.innerHTML = '';
        if (tables.length === 0) {
            intervalSelect.innerHTML = '<option value="">该市场无K线数据</option>';
            return;
        }
        tables.filter(function(item) { return item.interval !== '1t'; }).forEach(function(item) {
            var option = document.createElement('option');
            option.value = item.interval;
            option.innerText = item.interval.toUpperCase();
            intervalSelect.appendChild(option);
        });
        if (!intervalSelect.options.length) {
            intervalSelect.innerHTML = '<option value="">无可用周期</option>';
            return;
        }
        intervalSelect.disabled = false;
    }

    if (symbolInput) symbolInput.disabled = false;
    if (loadButton) loadButton.disabled = false;

    var symbols = await WSAPI.call('kline.symbols', { market: market });
    if (token !== activeLoadToken) return;

    if (symbolList && Array.isArray(symbols)) {
        symbols.forEach(function(item) {
            var option = document.createElement('option');
            option.value = item;
            symbolList.appendChild(option);
        });
    }

    await loadOverview();
}

async function onIntervalChange() {
    activeLoadToken++;
    await loadOverview();
}

async function loadOverview() {
    var token = activeLoadToken;
    var market = document.getElementById('kline-market').value;
    var interval = document.getElementById('kline-interval').value;
    if (!market || !interval) return;

    allOverviewData = [];
    renderedCount = 0;
    var container = document.getElementById('symbol-grid-container');
    if (container) container.innerHTML = '加载中...';

    allOverviewData = await WSAPI.call('kline.overview', { market: market, interval: interval });
    if (token !== activeLoadToken) return;
    if (!container) return;

    if (allOverviewData.length) sortSymbols(currentKlineSortKey, null);
    else container.innerHTML = '<div style="color:#667085">无数据</div>';
}

function sortSymbols(sortKey, buttonElement) {
    var nextSortKey = sortKey || currentKlineSortKey || 'symbol';
    if (buttonElement && nextSortKey === currentKlineSortKey) {
        currentKlineSortDirection = currentKlineSortDirection === 'asc' ? 'desc' : 'asc';
    } else if (nextSortKey !== currentKlineSortKey) {
        currentKlineSortDirection = nextSortKey === 'pct_change' ? 'desc' : 'asc';
    }
    currentKlineSortKey = nextSortKey;
    if (buttonElement) {
        var buttons = document.querySelectorAll('.symbol-list-controls .btn-xs');
        buttons.forEach(function(item) { item.classList.remove('active'); });
        buttonElement.classList.add('active');
    }

    allOverviewData.sort(function(a, b) {
        var result = 0;
        if (currentKlineSortKey === 'pct_change') {
            var left = Number(a.pct_change);
            var right = Number(b.pct_change);
            var leftValid = Number.isFinite(left);
            var rightValid = Number.isFinite(right);
            if (leftValid && rightValid && right !== left) result = left - right;
            else if (leftValid !== rightValid) result = leftValid ? -1 : 1;
        }
        if (result === 0) result = (a.symbol || '').localeCompare(b.symbol || '');
        return currentKlineSortDirection === 'desc' ? -result : result;
    });

    renderedCount = 0;
    var container = document.getElementById('symbol-grid-container');
    if (container) container.innerHTML = '';
    loadMoreSymbols();
}

function loadMoreSymbols() {
    var container = document.getElementById('symbol-grid-container');
    if (!container) return;

    var fragment = document.createDocumentFragment();
    var start = renderedCount;
    var end = Math.min(start + 100, allOverviewData.length);
    if (start >= end) return;

    for (var index = start; index < end; index++) {
        var item = allOverviewData[index];
        var card = document.createElement('div');
        card.className = 'symbol-card';
        if (item.symbol === currentSymbol) card.classList.add('selected');

        var close = Number(item.close);
        var pct = Number(item.pct_change);
        var priceText = Number.isFinite(close) ? close.toFixed(Math.abs(close) >= 1 ? 2 : 6) : '-';
        var pctText = Number.isFinite(pct) ? (pct > 0 ? '+' : '') + pct.toFixed(2) + '%' : '-';
        var pctClass = Number.isFinite(pct) ? (pct > 0 ? 'up bg-up' : (pct < 0 ? 'down bg-down' : '')) : '';

        card.innerHTML = '<div class="name" title="' + (item.short_name || '') + '">' + (item.short_name || '-') + '</div>'
            + '<div class="code">' + (item.symbol || '') + '</div>'
            + '<div class="price-info"><span class="price">' + priceText + '</span><span class="pct ' + pctClass + '">' + pctText + '</span></div>';
        card.onclick = function(selectedItem, selectedCard) {
            return function() {
                currentSymbol = selectedItem.symbol;
                container.querySelectorAll('.symbol-card').forEach(function(entry) { entry.classList.remove('selected'); });
                selectedCard.classList.add('selected');
                var input = document.getElementById('kline-symbol-manual');
                if (input) input.value = selectedItem.symbol;
                loadKline(selectedItem.symbol);
            };
        }(item, card);

        fragment.appendChild(card);
    }

    container.appendChild(fragment);
    renderedCount = end;
}

function loadKlineFromInput() {
    var input = document.getElementById('kline-symbol-manual');
    var symbol = input ? input.value.trim() : '';
    if (!symbol) return;
    currentSymbol = symbol;
    loadKline(symbol);
}

async function loadKline(symbol, fromPreset) {
    updateKlineQuery(symbol, fromPreset);
    if (!hasCompleteKlineDateRange()) return;
    if (!klineQuery.market || !klineQuery.interval || !klineQuery.symbol || !klineChart) return;

    currentSymbol = klineQuery.symbol;
    var token = ++activeLoadToken;

    try {
        klineChart.setSymbol({
            ticker: klineQuery.symbol,
            name: klineQuery.symbol,
            shortName: klineQuery.symbol,
            exchange: klineQuery.market
        });
        klineChart.setPeriod(parseIntervalToPeriod(klineQuery.interval));
        klineChart.resetData();
    } catch (error) {
        if (token !== activeLoadToken) return;
        alert('加载失败: ' + error.message);
    }
}
