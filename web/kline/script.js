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
// 优化：增加渲染延迟，减少批量渲染时的主线程阻塞
const RENDER_DELAY = 150;
// 优化：每次只渲染一块数据，避免批量更新卡顿
const BATCH_SIZE = 1;

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

    currentKlineData = { dates: [], ohlc: [], volumes: [], ticks: [] };
    klineChart.clear();
    initEmptyChart(symbol, barType);

    // === 关键修复1：非time bar禁用分页 ===
    const isTimeBar = barType === 'time';
    const disablePagination = !isTimeBar;  // 特殊bar不分页
    
    let offset = 0;
    const limit = disablePagination ? 1000000 : 250000;  // 特殊bar一次性加载100万条
    let total = 0;
    let loadedCount = 0;
    let hasMore = true;
    let isFirstRequest = true;
    _renderQueue = [];

    try {
        while (hasMore) {
            // === 计算分页 offset ===
            if (isTimeBar) {
                if (isFirstRequest) {
                    offset = 0;  // 第一请求获取 total
                } else {
                    // 倒序：从最新往最早加载
                    offset = Math.max(0, total - loadedCount - limit);
                }
            } else {
                // 特殊 bar：正序加载，从最早开始（但禁用分页，只请求一次）
                offset = 0;
            }
            
            const params = {
                market: market, interval: interval, symbol: symbol,
                range_type: rangeType, adj: adjType, bar_type: barType,
                offset: offset, limit: limit
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

            // === 第一请求后获取 total，time bar 重定向到最新块 ===
            if (total === 0 && result.total) {
                total = result.total;
                
                if (isTimeBar && isFirstRequest && total > limit) {
                    const correctOffset = total - limit;
                    if (correctOffset > 0 && correctOffset !== offset) {
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

            // === 拼接方向 + 优化：使用更高效的数组操作 ===
            if (loadedCount === 0) {
                // 第一块：直接赋值（使用slice避免引用）
                currentKlineData.dates = newChunk.dates.slice();
                currentKlineData.ohlc = newChunk.ohlc.slice();
                currentKlineData.volumes = newChunk.volumes.slice();
                currentKlineData.ticks = newChunk.ticks.slice();
            } else if (isTimeBar) {
                // time bar：新块是更早的数据，拼接到前面
                // 优化：使用 unshift + spread 批量前置插入，比多次 concat 更高效
                currentKlineData.dates.unshift(...newChunk.dates);
                currentKlineData.ohlc.unshift(...newChunk.ohlc);
                currentKlineData.volumes.unshift(...newChunk.volumes);
                currentKlineData.ticks.unshift(...newChunk.ticks);
            } else {
                // 特殊 bar：拼接到后面
                currentKlineData.dates.push(...newChunk.dates);
                currentKlineData.ohlc.push(...newChunk.ohlc);
                currentKlineData.volumes.push(...newChunk.volumes);
                currentKlineData.ticks.push(...newChunk.ticks);
            }

            loadedCount += newChunk.dates.length;
            _renderQueue.push({ chunk: newChunk, isFirst: loadedCount === newChunk.dates.length && loadedCount > 0 });

            // 节流渲染 - 优化：更细粒度控制
            if (_renderQueue.length >= BATCH_SIZE) {
                await _flushRenderQueue();
            }

            // === 关键修复2：hasMore 判断 ===
            if (disablePagination) {
                // 特殊 bar：只加载一次
                hasMore = false;
            } else if (isTimeBar) {
                // time bar: offset=0 或数据不足表示已加载完
                if (offset <= 0 || result.data.length < limit) {
                    hasMore = false;
                }
            } else {
                // 备用逻辑（理论上不会执行）
                if (result.more === false || result.data.length < limit) {
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
    
    const totalPoints = currentKlineData.dates.length;
    
    // 修复：xAxis 必须包含完整配置项，避免 axis undefined 错误
    const xAxisConfig = [
        { 
            type: 'category', 
            data: currentKlineData.dates, 
            boundaryGap: false, 
            axisLine: { onZero: false }, 
            splitLine: { show: false }, 
            min: 'dataMin', 
            max: 'dataMax',
            axisLabel: { show: true }
        },
        { 
            type: 'category', 
            gridIndex: 1, 
            data: currentKlineData.dates, 
            boundaryGap: false, 
            axisLine: { onZero: false }, 
            axisTick: { show: false }, 
            splitLine: { show: false }, 
            axisLabel: { show: false },
            min: 'dataMin', 
            max: 'dataMax' 
        }
    ];
    
    // 构建 option 基础配置（xAxis 和 series 必须每次都传）
    const option = {
        xAxis: xAxisConfig,
        series: [
            { data: currentKlineData.ohlc, silent: true, animation: false },
            { data: seriesData, silent: true, animation: false }
        ]
    };
    
    // 🔑 关键修复：只在首次加载时设置 dataZoom 的 start/end
    // 后续增量加载时不传 dataZoom，ECharts 会自动保持用户当前的缩放状态
    if (isFirstChunk) {
        const zoomStart = totalPoints <= 25000 ? 0 : 80;
        const zoomEnd = 100;
        option.dataZoom = [
            { type: 'inside', xAxisIndex: [0, 1], start: zoomStart, end: zoomEnd, filterMode: 'weakFilter' },
            { show: true, xAxisIndex: [0, 1], type: 'slider', bottom: '5%', start: zoomStart, end: zoomEnd, filterMode: 'weakFilter' }
        ];
    }
    // 非首次加载时，option 中不包含 dataZoom 字段，setOption 会保持现有缩放状态
    
    // 使用 lazyUpdate 减少重绘开销，notMerge: false 保证配置合并而非覆盖
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
    // 优化：提升性能参数阈值，启用采样优化
    const performanceOpts = {
        large: true,
        largeThreshold: 100000,
        progressive: 25000,        // 优化：提高渐进渲染阈值
        progressiveThreshold: 100000,  // 优化：大数据量启用采样
        progressiveChunkMode: 'mod', // 分块模式
        
        // 性能优化
        animation: false,          // 关闭动画
        hoverAnimation: false,     // 关闭悬停动画
        silent: true,              // 静默模式（关闭交互）
        sampling: 'lttb'          // 优化：添加 LTTB 降采样算法
    };
    
    // 修复：xAxis 配置必须完整，两个坐标轴都要有 type: 'category'
    const xAxisConfig = [
        // 主坐标轴：显示日期
        { 
            type: 'category', 
            data: [], 
            boundaryGap: false, 
            axisLine: { onZero: false }, 
            splitLine: { show: false }, 
            min: 'dataMin', 
            max: 'dataMax',
            axisLabel: { show: true }
        },
        // 副坐标轴：隐藏日期，避免重复
        { 
            type: 'category', 
            gridIndex: 1, 
            data: [], 
            boundaryGap: false, 
            axisLine: { onZero: false }, 
            axisTick: { show: false }, 
            splitLine: { show: false }, 
            axisLabel: { show: false },
            min: 'dataMin', 
            max: 'dataMax' 
        }
    ];
    
    const option = {
        title: { text: symbol.toUpperCase(), left: 'center' },
        tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
        legend: { data: ['K线', barType === 'time' ? '成交量' : '时间消耗'], bottom: 10 },
        axisPointer: { link: [{ xAxisIndex: 'all' }] },
        grid: [
            { left: '10%', right: '8%', top: '10%', height: '50%' },
            { left: '10%', right: '8%', top: '70%', height: '15%' }
        ],
        xAxis: xAxisConfig,
        yAxis: [
            { scale: true, splitArea: { show: true } },
            { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } }
        ],
        dataZoom: [
            // 优化：添加 filterMode 减少缩放重绘
            { type: 'inside', xAxisIndex: [0, 1], start: 80, end: 100, filterMode: 'weakFilter' },
            { show: true, xAxisIndex: [0, 1], type: 'slider', bottom: '5%', start: 80, end: 100, filterMode: 'weakFilter' }
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