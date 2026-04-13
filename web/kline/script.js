// Kline Logic
let klineChart = null;
let allOverviewData = [];
let renderedCount = 0;
const PAGE_SIZE = 100;
let fullKlineData = [];
let currentSortKey = 'symbol';
let currentSymbol = '';

// 渲染节流控制
let _renderTimer = null;
let _renderQueue = [];
const RENDER_DELAY = 80;
const BATCH_SIZE = 3;

function init_kline() {
    const chartDom = document.getElementById('kline-chart-area');
    if (chartDom && typeof echarts !== 'undefined') {
        if (klineChart) {
            klineChart.dispose();
        }
        klineChart = echarts.init(chartDom);
        window.addEventListener('resize', () => klineChart && klineChart.resize());
    } else {
        console.error("ECharts load failed");
    }
    populateMarkets();
    const container = document.getElementById('symbol-grid-container');
    if (container) {
        container.addEventListener('scroll', () => {
            if (container.scrollTop + container.clientHeight >= container.scrollHeight - 20) {
                loadMoreSymbols();
            }
        });
    }
}

async function populateMarkets() {
    try {
        const data = await WSAPI.get('/tasks', {}, false);
        const markets = Object.keys(data).filter(k => k !== "System");
        const select = document.getElementById('kline-market');
        if (!select) return;
        select.innerHTML = '<option>选择市场</option>';
        markets.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            opt.innerText = m.toUpperCase();
            select.appendChild(opt);
        });
    } catch (e) {
        console.error("Failed to load markets", e);
    }
}

async function onMarketChange() {
    const market = document.getElementById('kline-market').value;
    const intervalSelect = document.getElementById('kline-interval');
    const symbolInput = document.getElementById('kline-symbol-manual');
    const loadBtn = document.getElementById('btn-load-kline');
    const symbolList = document.getElementById('symbol-list');
    
    if (intervalSelect) {
        intervalSelect.innerHTML = '加载中...';
        intervalSelect.disabled = true;
    }
    if (symbolInput) symbolInput.disabled = true;
    if (loadBtn) loadBtn.disabled = true;
    if (symbolInput) symbolInput.value = '';
    if (symbolList) symbolList.innerHTML = '';
    
    allOverviewData = [];
    renderedCount = 0; 
    const container = document.getElementById('symbol-grid-container');
    if (container) container.innerHTML = '';
    
    if (!market) return;
    
    try {
        const tables = await WSAPI.get('/kline/tables/' + encodeURIComponent(market), {}, false);
        if (intervalSelect) {
            intervalSelect.innerHTML = '';
            if (!tables || tables.length === 0) {
                intervalSelect.innerHTML = '<option>该市场无K线数据</option>';
                return;
            }
            tables.forEach(t => {
                const opt = document.createElement('option');
                opt.value = t.interval;
                opt.innerText = t.interval.toUpperCase();
                intervalSelect.appendChild(opt);
            });
            intervalSelect.disabled = false;
        }
        if (symbolInput) symbolInput.disabled = false;
        if (loadBtn) loadBtn.disabled = false;
        
        const symbols = await WSAPI.get('/kline/symbols/' + encodeURIComponent(market), {}, false);
        if (symbolList && symbols && symbols.length > 0) {
            symbols.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s;
                symbolList.appendChild(opt);
            });
        }
        await loadOverview();
    } catch (e) {
        console.error(e);
        if (intervalSelect) intervalSelect.innerHTML = '<option>加载失败</option>';
    }
}

async function onIntervalChange() {
    await loadOverview();
}

async function loadOverview() {
    const market = document.getElementById('kline-market').value;
    const interval = document.getElementById('kline-interval').value;
    if (!market || !interval) return;
    
    allOverviewData = [];
    renderedCount = 0;
    const container = document.getElementById('symbol-grid-container');
    if (container) container.innerHTML = '加载中...';
    
    try {
        const data = await WSAPI.get('/kline/overview', { market, interval }, false);
        if (data && data.length > 0) {
            allOverviewData = data;
            sortSymbols(currentSortKey, null, false);
        } else {
            if (container) container.innerHTML = '<div style="color:#999">无数据</div>';
        }
    } catch (e) {
        console.error("Load overview failed", e);
        if (container) container.innerHTML = '<div style="color:red">加载失败</div>';
    }
}

function sortSymbols(key, btnElement, needReload) {
    currentSortKey = key;
    if (btnElement) {
        const btns = document.querySelectorAll('.symbol-list-controls .btn-xs');
        btns.forEach(b => b.classList.remove('active'));
        btnElement.classList.add('active');
    }
    if (key === 'pct_change') {
        allOverviewData.sort((a, b) => (b.pct_change || -999) - (a.pct_change || -999));
    } else {
        allOverviewData.sort((a, b) => (a.symbol || '').localeCompare(b.symbol || ''));
    }
    renderedCount = 0;
    const container = document.getElementById('symbol-grid-container');
    if (container) container.innerHTML = '';
    loadMoreSymbols();
}

function loadMoreSymbols() {
    const container = document.getElementById('symbol-grid-container');
    if (!container) return;
    const fragment = document.createDocumentFragment();
    const start = renderedCount;
    const end = Math.min(start + PAGE_SIZE, allOverviewData.length);
    if (start >= end) return;
    
    for (let i = start; i < end; i++) {
        const item = allOverviewData[i];
        const card = document.createElement('div');
        card.className = 'symbol-card';
        if (item.symbol === currentSymbol) card.classList.add('selected');
        const hasPrice = item.close !== null && item.close !== undefined;
        const pct = item.pct_change || 0;
        const isUp = pct >= 0;
        const colorClass = isUp ? 'up' : 'down';
        const bgClass = isUp ? 'bg-up' : 'bg-down';
        let priceHtml = '-';
        if (hasPrice) {
            priceHtml = `<span class="price ${colorClass}">${item.close.toFixed(2)}</span> <span class="pct ${bgClass} ${colorClass}">${isUp ? '+' : ''}${pct.toFixed(2)}%</span>`;
        }
        card.innerHTML = `<div class="name" title="${item.short_name || ''}">${item.short_name || '-'}</div> <div class="code">${item.symbol}</div> <div class="price-info">${priceHtml}</div>`;
        card.onclick = () => {
            currentSymbol = item.symbol;
            container.querySelectorAll('.symbol-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            const input = document.getElementById('kline-symbol-manual');
            if (input) input.value = item.symbol;
            loadKline(item.symbol);
        };
        fragment.appendChild(card);
    }
    container.appendChild(fragment);
    renderedCount = end;
}

function onBarTypeChange() {
    const barType = document.getElementById('kline-bar-type').value;
    const thresholdGroup = document.getElementById('kline-threshold-group');
    const thresholdInput = document.getElementById('kline-bar-threshold');
    if (!thresholdGroup || !thresholdInput) return;
    if (barType === 'time') {
        thresholdGroup.style.display = 'none';
    } else {
        thresholdGroup.style.display = 'block';
        if (barType === 'volume') {
            thresholdInput.placeholder = "如 1000000";
            thresholdInput.value = "1000000";
            thresholdInput.step = "any";
        } else if (barType === 'cusum') {
            thresholdInput.placeholder = "如 0.02 (2%)";
            thresholdInput.value = "0.02";
            thresholdInput.step = "0.01";
        }
    }
}

// 全局数据缓存
let currentKlineData = { dates: [], ohlc: [], volumes: [], ticks: [] };

async function loadKlineFromInput() {
    const input = document.getElementById('kline-symbol-manual');
    const symbol = input ? input.value.trim() : '';
    if(symbol) {
        currentSymbol = symbol;
        loadKline(symbol);
    }
}

async function loadKline(symbol) {
    if(!symbol) return;
    const marketEl = document.getElementById('kline-market');
    const intervalEl = document.getElementById('kline-interval');
    const rangeEl = document.getElementById('kline-range');
    const adjEl = document.getElementById('kline-adj');
    const barTypeEl = document.getElementById('kline-bar-type');
    const thresholdEl = document.getElementById('kline-bar-threshold');
    
    const market = marketEl ? marketEl.value : '';
    const interval = intervalEl ? intervalEl.value : '';
    const rangeType = rangeEl ? rangeEl.value : '1m';
    const adjType = adjEl ? adjEl.value : 'none';
    const barType = barTypeEl ? barTypeEl.value : 'time';
    const threshold = (barType !== 'time' && thresholdEl && thresholdEl.value) ? parseFloat(thresholdEl.value) : null;
    
    if (!market || !interval) return;
    
    if (!klineChart) {
        init_kline();
        if(!klineChart) return;
    }

    // 重置状态 
    currentKlineData = { dates: [], ohlc: [], volumes: [], ticks: [] };
    klineChart.clear();
    initEmptyChart(symbol, barType);

    let offset = 0;
    const limit = 50000; 
    let total = 0;
    let hasMore = true;
    _renderQueue = [];

    try {
        while (hasMore) {
            const params = {
                market: market, interval: interval, symbol: symbol,
                range_type: rangeType, adj: adjType, bar_type: barType,
                offset: offset, limit: limit
            };
            if (threshold !== null) params.bar_threshold = threshold;

            const result = await WSAPI.get('/kline/data', params, false);
            
            if (result.detail) throw new Error(result.detail);

            if (!result.data || result.data.length === 0) {
                if (offset === 0) {
                    klineChart.setOption({ 
                        title: { text: '无数据', subtext: '数据库中未找到记录', left: 'center', top: 'center' } 
                    });
                }
                break;
            }

            if (total === 0 && result.total) total = result.total;

            const newChunk = parseKlineData(result.data);

            currentKlineData.dates.push(...newChunk.dates);
            currentKlineData.ohlc.push(...newChunk.ohlc);
            currentKlineData.volumes.push(...newChunk.volumes);
            currentKlineData.ticks.push(...newChunk.ticks);

            _renderQueue.push({ chunk: newChunk, isFirst: offset === 0 });

            // 节流渲染
            if (_renderQueue.length >= BATCH_SIZE || !result.more) {
                await _flushRenderQueue();
            }

            if (result.data.length < limit) {
                hasMore = false;
            } else {
                offset += limit;
                if (currentKlineData.dates.length >= 1500000) { 
                    console.warn("Reached client-side memory limit.");
                    hasMore = false;
                }
            }
        }
        await _flushRenderQueue();

    } catch (e) {
        console.error("Load kline failed", e);
        alert("加载失败: " + e.message);
        if (klineChart && currentKlineData.dates.length === 0) {
            klineChart.clear();
            klineChart.setOption({ 
                title: { text: '加载错误', subtext: e.message, left: 'center', top: 'center' } 
            });
        }
    }
}

async function _flushRenderQueue() {
    if (_renderTimer) {
        return new Promise(resolve => setTimeout(resolve, RENDER_DELAY));
    }
    return new Promise(resolve => {
        _renderTimer = setTimeout(() => {
            while (_renderQueue.length) {
                const { chunk, isFirst } = _renderQueue.shift();
                _appendDataSilent(chunk, document.getElementById('kline-bar-type')?.value || 'time', isFirst);
            }
            _renderTimer = null;
            resolve();
        }, RENDER_DELAY);
    });
}

function _appendDataSilent(newChunk, barType, isFirstChunk) {
    const seriesData = barType === 'time' ? newChunk.volumes : newChunk.ticks;
    const option = {
        xAxis: [
            { data: currentKlineData.dates },
            { data: currentKlineData.dates }
        ],
        series: [
            { data: currentKlineData.ohlc, silent: !isFirstChunk, animation: false },
            { data: seriesData, silent: !isFirstChunk, animation: false }
        ]
    };
    klineChart.setOption(option, { notMerge: false, lazyUpdate: true });
}

function parseKlineData(rawData) {
    const dates = [];
    const ohlc = [];
    const volumes = [];
    const ticks = [];
    rawData.forEach(item => {
        dates.push(item.date);
        ohlc.push([
            parseFloat(item.open) || 0,
            parseFloat(item.close) || 0,
            parseFloat(item.low) || 0,
            parseFloat(item.high) || 0
        ]);
        volumes.push(parseFloat(item.volume) || 0);
        ticks.push(parseFloat(item.ticks) || 1);
    });
    return { dates, ohlc, volumes, ticks };
}

function initEmptyChart(symbol, barType) {
    const performanceOpts = {
        large: true,
        largeThreshold: 2000,
        progressive: 2000,
        progressiveThreshold: 10000,
        animation: false
    };
    const option = {
        title: { text: symbol.toUpperCase(), left: 'center' },
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        legend: { data: ['K线', barType === 'time' ? '成交量' : '时间消耗'], bottom: 10 },
        axisPointer: { link: [{ xAxisIndex: 'all' }] },
        grid: [
            { left: '10%', right: '8%', top: '10%', height: '50%' },
            { left: '10%', right: '8%', top: '70%', height: '15%' }
        ],
        xAxis: [
            { type: 'category', data: [], boundaryGap: false, axisLine: { onZero: false }, splitLine: { show: false }, min: 'dataMin', max: 'dataMax' },
            { type: 'category', gridIndex: 1, data: [], boundaryGap: false, axisLine: { onZero: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false }, min: 'dataMin', max: 'dataMax' }
        ],
        yAxis: [
            { scale: true, splitArea: { show: true } },
            { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } }
        ],
        dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1], start: 80, end: 100 },
            { show: true, xAxisIndex: [0, 1], type: 'slider', bottom: '5%', start: 80, end: 100 }
        ],
        series: [
            {
                name: 'K线', type: 'candlestick', data: [],
                ...performanceOpts,
                itemStyle: { color: '#ef5350', color0: '#26a69a', borderColor: '#ef5350', borderColor0: '#26a69a' }
            },
            {
                name: barType === 'time' ? '成交量' : '时间消耗',
                type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: [],
                ...performanceOpts,
                itemStyle: { color: barType === 'time' ? '#26a69a' : '#5470c6' }
            }
        ]
    };
    klineChart.setOption(option);
}