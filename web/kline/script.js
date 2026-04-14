// web/kline/script.js
// Kline Logic - Reverse chunk loading with correct time axis
let klineChart = null;
let allOverviewData = [];
let renderedCount = 0;
const PAGE_SIZE = 100;
let fullKlineData = [];
let currentSortKey = 'symbol';
let currentSymbol = '';

let _renderTimer = null;
let _renderQueue = [];
const RENDER_DELAY = 80;
const BATCH_SIZE = 3;

// 全局数据缓存 - 只声明一次
let currentKlineData = { dates: [], ohlc: [], volumes: [], ticks: [] };

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
        const data = await WSAPI.get('/tasks');
        const markets = Object.keys(data).filter(k => {
            return k && typeof k === 'string' && k.trim() && !k.startsWith('_') && k !== 'System';
        });
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
        const tables = await WSAPI.get('/kline/tables', { market: market });
        if (!Array.isArray(tables)) {
            console.error('tables is not an array:', tables);
            if (intervalSelect) intervalSelect.innerHTML = '<option>数据格式错误</option>';
            return;
        }
        if (intervalSelect) {
            intervalSelect.innerHTML = '';
            if (tables.length === 0) {
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
        
        const symbols = await WSAPI.get('/kline/symbols', { market: market });
        if (symbolList && Array.isArray(symbols) && symbols.length > 0) {
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
        const data = await WSAPI.get('/kline/overview', { market, interval });
        if (Array.isArray(data) && data.length > 0) {
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

    // 关键修复：直接赋值，不要重复声明
    currentKlineData = { dates: [], ohlc: [], volumes: [], ticks: [] };
    klineChart.clear();
    initEmptyChart(symbol, barType);

    // 加载策略：time bar 倒序分页（先加载最新块），特殊 bar 正序分页（从最早计算）
    const isTimeBar = barType === 'time';
    
    let offset = 0;
    const limit = 50000; 
    let total = 0;
    let loadedCount = 0;
    let hasMore = true;
    let isFirstRequest = true;
    _renderQueue = [];

    try {
        while (hasMore) {
            // === 关键修复1：计算分页 offset ===
            if (isTimeBar) {
                if (isFirstRequest) {
                    // 第一请求：offset=0 获取 total
                    offset = 0;
                } else {
                    // 后续请求：从最新往最早加载
                    // offset = total - 已加载数 - 当前块大小
                    offset = Math.max(0, total - loadedCount - limit);
                }
            } else {
                // 特殊 bar：正序加载，从最早开始计算
                offset = loadedCount;
            }
            
            const params = {
                market: market, interval: interval, symbol: symbol,
                range_type: rangeType, adj: adjType, bar_type: barType,
                offset: offset, limit: limit, sort_order: 'asc'  // 始终正序查询
            };
            if (threshold !== null) params.bar_threshold = threshold;

            const result = await WSAPI.get('/kline/data', params);
            
            if (result.error) throw new Error(result.error);
            if (result.detail) throw new Error(result.detail);

            if (!result.data || result.data.length === 0) {
                if (loadedCount === 0) {
                    klineChart.setOption({ 
                        title: { text: '无数据', subtext: '数据库中未找到记录', left: 'center', top: 'center' } 
                    });
                }
                break;
            }

            // === 关键修复2：第一请求后获取 total，time bar 重新定位到最新块 ===
            if (total === 0 && result.total) {
                total = result.total;
                
                if (isTimeBar && isFirstRequest && total > limit) {
                    // 计算最新块的 offset
                    const correctOffset = total - limit;
                    if (correctOffset > 0 && correctOffset !== offset) {
                        // 重新请求正确的最新块
                        params.offset = correctOffset;
                        const newResult = await WSAPI.get('/kline/data', params);
                        if (newResult.data && newResult.data.length > 0) {
                            result.data = newResult.data;
                            result.total = newResult.total;
                            offset = correctOffset;
                        }
                    }
                }
            }

            isFirstRequest = false;

            const newChunk = parseKlineData(result.data);
            // SQL 正序查询，块内已是 [旧→新]，不需要 reverse（保持用户注释掉的逻辑）

            // === 关键修复3：拼接方向 ===
            if (loadedCount === 0) {
                // 第一块：直接赋值
                currentKlineData.dates = [...newChunk.dates];
                currentKlineData.ohlc = [...newChunk.ohlc];
                currentKlineData.volumes = [...newChunk.volumes];
                currentKlineData.ticks = [...newChunk.ticks];
            } else if (isTimeBar) {
                // time bar 后续块：新块是更早的数据，拼接到前面
                // [更早数据] + [已有数据] = [最旧...最新] ✓
                currentKlineData.dates = newChunk.dates.concat(currentKlineData.dates);
                currentKlineData.ohlc = newChunk.ohlc.concat(currentKlineData.ohlc);
                currentKlineData.volumes = newChunk.volumes.concat(currentKlineData.volumes);
                currentKlineData.ticks = newChunk.ticks.concat(currentKlineData.ticks);
            } else {
                // 特殊 bar：新块是更晚的数据，拼接到后面（保持用户注释掉的 push 逻辑）
                currentKlineData.dates.push(...newChunk.dates);
                currentKlineData.ohlc.push(...newChunk.ohlc);
                currentKlineData.volumes.push(...newChunk.volumes);
                currentKlineData.ticks.push(...newChunk.ticks);
            }

            loadedCount += newChunk.dates.length;
            _renderQueue.push({ chunk: newChunk, isFirst: loadedCount === newChunk.dates.length });

            // 节流渲染
            if (_renderQueue.length >= BATCH_SIZE) {
                await _flushRenderQueue();
            }

            // === 关键修复4：判断是否还有更多数据 ===
            if (isTimeBar) {
                // time bar: offset=0 或数据不足表示已加载完
                if (offset <= 0 || result.data.length < limit) {
                    hasMore = false;
                }
            } else {
                // 特殊 bar: 数据不足表示已加载完
                if (result.data.length < limit) {
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
    const seriesData = barType === 'time' ? currentKlineData.volumes : currentKlineData.ticks;
    
    // === 关键修复5：dataZoom 始终聚焦右侧（显示最新数据）===
    // 无论加载顺序如何，currentKlineData 始终是 [最旧...最新]
    // dataZoom 默认显示最后 20%，让用户第一眼看到最新数据
    const totalPoints = currentKlineData.dates.length;
    const zoomStart = totalPoints <= 50000 ? 0 : 80;  // 数据少时显示全部
    const zoomEnd = 100;
    
    const option = {
        xAxis: [
            { data: currentKlineData.dates },
            { data: currentKlineData.dates }
        ],
        series: [
            { data: currentKlineData.ohlc, silent: !isFirstChunk, animation: false },
            { data: seriesData, silent: !isFirstChunk, animation: false }
        ],
        dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1], start: zoomStart, end: zoomEnd },
            { show: true, xAxisIndex: [0, 1], type: 'slider', bottom: '5%', start: zoomStart, end: zoomEnd }
        ]
    };
    // 关键：使用 lazyUpdate 和 notMerge:false 避免图表闪烁
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