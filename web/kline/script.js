// Kline Logic
let klineChart = null;
let allOverviewData = []; 
let renderedCount = 0;
const PAGE_SIZE = 100; // 概览列表分页

// 新增：全量 K 线数据缓存
let fullKlineData = []; 
let currentSortKey = 'symbol';
let currentSymbol = '';

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
    container.addEventListener('scroll', () => {
        if (container.scrollTop + container.clientHeight >= container.scrollHeight - 20) {
            loadMoreSymbols();
        }
    });
}

async function populateMarkets() {
    try {
        const res = await fetch('/api/tasks');
        const data = await res.json();
        const markets = Object.keys(data).filter(k => k !== "System");
        const select = document.getElementById('kline-market');
        select.innerHTML = '<option value="">选择市场</option>';
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
    intervalSelect.innerHTML = '<option value="">加载中...</option>';
    intervalSelect.disabled = true;
    symbolInput.disabled = true;
    loadBtn.disabled = true;
    symbolInput.value = '';
    symbolList.innerHTML = '';
    allOverviewData = [];
    renderedCount = 0;
    document.getElementById('symbol-grid-container').innerHTML = '';
    if (!market) return;
    try {
        // 获取表
        const tablesRes = await fetch(`/api/kline/tables/${market}`);
        const tables = await tablesRes.json();
        intervalSelect.innerHTML = '';
        if (!tables || tables.length === 0) {
            intervalSelect.innerHTML = '<option value="">该市场无K线数据</option>';
            return;
        }
        tables.forEach(t => {
            const opt = document.createElement('option');
            opt.value = t.interval;
            opt.innerText = t.interval.toUpperCase();
            intervalSelect.appendChild(opt);
        });
        intervalSelect.disabled = false;
        symbolInput.disabled = false;
        loadBtn.disabled = false;
        // 获取代码
        const symbolsRes = await fetch(`/api/kline/symbols/${market}`);
        const symbols = await symbolsRes.json();
        if (symbols && symbols.length > 0) {
            symbols.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s;
                symbolList.appendChild(opt);
            });
        }
        await loadOverview();
    } catch (e) {
        console.error(e);
        intervalSelect.innerHTML = '<option value="">加载失败</option>';
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
    document.getElementById('symbol-grid-container').innerHTML = '加载中...';
    try {
        const response = await fetch(`/api/kline/overview?market=${market}&interval=${interval}`);
        const data = await response.json();
        if (data && data.length > 0) {
            allOverviewData = data;
            sortSymbols(currentSortKey, null, false);
        } else {
            document.getElementById('symbol-grid-container').innerHTML = '<div style="padding:20px; text-align:center; color:var(--text-muted)">无数据</div>';
        }
    } catch (e) {
        console.error("Load overview failed", e);
        document.getElementById('symbol-grid-container').innerHTML = '<div style="padding:20px; text-align:center; color:red">加载失败</div>';
    }
}
function sortSymbols(key, btnElement, needReload = true) {
    currentSortKey = key;
    if (btnElement) {
        document.querySelectorAll('.symbol-list-controls .btn-xs').forEach(b => b.classList.remove('active'));
        btnElement.classList.add('active');
    }
    if (key === 'pct_change') {
        allOverviewData.sort((a, b) => (b.pct_change || -999) - (a.pct_change || -999));
    } else {
        allOverviewData.sort((a, b) => (a.symbol || '').localeCompare(b.symbol || ''));
    }
    renderedCount = 0;
    document.getElementById('symbol-grid-container').innerHTML = '';
    loadMoreSymbols();
}
function loadMoreSymbols() {
    const container = document.getElementById('symbol-grid-container');
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
            priceHtml = `<span class="price ${colorClass}">${item.close.toFixed(2)}</span>
                         <span class="pct ${bgClass} ${colorClass}">${isUp ? '+' : ''}${pct.toFixed(2)}%</span>`;
        }
        card.innerHTML = `
            <div class="name" title="${item.short_name || ''}">${item.short_name || '-'}</div>
            <div class="code">${item.symbol}</div>
            <div class="price-info">${priceHtml}</div>
        `;
        card.onclick = () => {
            currentSymbol = item.symbol;
            container.querySelectorAll('.symbol-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            document.getElementById('kline-symbol-manual').value = item.symbol;
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

// 全局数据缓存，用于增量更新
let currentKlineData = {
    dates: [],
    ohlc: [],
    volumes: [],
    ticks: []
};

async function loadKlineFromInput() {
    const symbol = document.getElementById('kline-symbol-manual').value.trim();
    if(symbol) {
        currentSymbol = symbol;
        loadKline(symbol);
    }
}

async function loadKline(symbol) {
    if(!symbol) return;
    const market = document.getElementById('kline-market').value;
    const interval = document.getElementById('kline-interval').value;
    const rangeType = document.getElementById('kline-range').value;
    const adjSelect = document.getElementById('kline-adj');
    const adjType = adjSelect ? adjSelect.value : 'none';
    const barType = document.getElementById('kline-bar-type').value;
    const thresholdInput = document.getElementById('kline-bar-threshold');
    const threshold = (barType !== 'time' && thresholdInput.value) ? parseFloat(thresholdInput.value) : null;

    if (!market || !interval) return;
    if (!klineChart) {
        init_kline();
        if(!klineChart) return;
    }

    // 1. 重置状态 
    currentKlineData = { dates: [], ohlc: [], volumes: [], ticks: [] };
    klineChart.clear();

    // 初始化图表配置（空数据），设置大数优化参数
    initEmptyChart(symbol, barType);

    // ✅ 已移除 klineChart.showLoading(...)

    let offset = 0;
    const limit = 50000; 
    let total = 0;
    let hasMore = true;

    try {
        while (hasMore) {
            const params = new URLSearchParams({
                market: market, interval: interval, symbol: symbol,
                range_type: rangeType, adj: adjType, bar_type: barType,
                offset: offset, limit: limit
            });
            
            if (threshold !== null) params.append('bar_threshold', threshold);

            const response = await fetch(`/api/kline/data?${params.toString()}`);
            const result = await response.json();
            
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

            appendDataToChart(newChunk, barType, offset === 0);

            // ✅ 已移除 hideLoading / showLoading 进度更新逻辑
            // 如果需要保留进度提示但不遮挡图表，可改为 console.log 或更新页面上的独立状态栏
            const progress = total > 0 ? Math.round((currentKlineData.dates.length / total) * 100) : 50;
            // console.log(`加载进度: ${progress}%`); 

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

        // ✅ 已移除 klineChart.hideLoading();

    } catch (e) {
        console.error("Load kline failed ", e);
        alert("加载失败: " + e.message);
        if (klineChart) {
            // ✅ 已移除 klineChart.hideLoading();
            if (currentKlineData.dates.length === 0) {
                klineChart.clear();
                klineChart.setOption({ 
                    title: { text: '加载错误', subtext: e.message, left: 'center', top: 'center' } 
                });
            }
        }
    }
}
/**
 * 解析原始数据为图表所需格式
 */
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

/**
 * 初始化一个空的图表框架，配置好大数优化参数
 */
function initEmptyChart(symbol, barType) {
    const performanceOpts = {
        large: true,
        largeThreshold: 2000,
        progressive: 2000,       // 渐进式渲染数量
        progressiveThreshold: 10000,
        animation: false
    };

    const option = {
        title: { text: symbol.toUpperCase(), left: 'center' },
        tooltip: { 
            trigger: 'axis', 
            axisPointer: { type: 'cross' }
        },
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
            { type: 'inside', xAxisIndex: [0, 1], start: 80, end: 100 }, // 默认显示最新的20%
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

/**
 * 将新数据追加到图表
 * @param {Object} newChunk - 新分块数据 { dates, ohlc, volumes, ticks }
 * @param {string} barType - bar类型
 * @param {boolean} isFirstChunk - 是否是第一块数据
 */
function appendDataToChart(newChunk, barType, isFirstChunk) {
    // ECharts 增量数据格式
    // 注意：对于类目轴，X轴数据不能简单的 append，因为 ECharts 内部需要索引映射。
    // 最稳妥的方式是更新整个 X 轴的 data，或者确保 appendData 的正确使用。
    // 但对于几十万数据，频繁 setOption 全量 X 轴会有性能问题。
    // 折中方案：X 轴数据整体更新（因为字符串数组引用传递很快），Y 轴数据增量追加。

    const seriesData = barType === 'time' ? newChunk.volumes : newChunk.ticks;

    const option = {
        xAxis: [
            // X轴必须全量更新，否则新数据无法映射到正确的位置
            // 但因为我们使用了 min/max: 'dataMin'/'dataMax'，这会自动调整范围
            { data: currentKlineData.dates },
            { data: currentKlineData.dates }
        ],
        series: [
            // K线数据增量追加
            { data: currentKlineData.ohlc },
            // 成交量/指标数据增量追加
            { data: seriesData } 
        ]
    };

    // 使用 notMerge: false (默认) 来合并数据
    // 但这里有个技巧：如果直接传全量数据，其实不是增量渲染。
    // ECharts 并没有完美的 "appendData" API 给类目轴使用。
    // 在大数据模式下，直接 setOption 全量数据其实是经过优化的，只要开启了 large: true。
    
    if (isFirstChunk) {
        // 第一块直接设置
        klineChart.setOption(option);
    } else {
        // 后续块：为了防止界面闪烁，我们尽量保持缩放状态
        // 获取当前缩放状态
        const currentOption = klineChart.getOption();
        // 保持当前的 start/end，防止自动跳转
        // 但如果用户拉到了最右边，新数据来了应该自动跟进吗？
        // 这里为了简单，直接 setOption，ECharts 内部会处理 diff
        
        // 只有当数据量非常大时，频繁 setOption 才会卡。
        // 我们可以稍微节流一下，或者直接 set。
        // 由于我们设置了 large: true，这里直接 setOption 全量数据通常是可接受的。
        klineChart.setOption(option);
    }
}