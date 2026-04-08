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

function destroy_kline() {
    if (klineChart) {
        klineChart.dispose();
        klineChart = null;
    }
    allOverviewData = [];
    renderedCount = 0;
    fullKlineData = []; // 清空缓存
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
async function loadKlineFromInput() {
    const symbol = document.getElementById('kline-symbol-manual').value.trim();
    if(symbol) {
        currentSymbol = symbol;
        loadKline(symbol);
    }
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

async function loadKlineFromInput() {
    const symbol = document.getElementById('kline-symbol-manual').value.trim();
    if(symbol) {
        currentSymbol = symbol;
        loadKline(symbol);
    }
}

// 核心改造：分块加载逻辑
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

    // 重置状态
    fullKlineData = [];
    klineChart.clear();
    klineChart.showLoading('default', { text: '正在加载数据 (0%)...', color: '#c23531', textColor: '#fff', maskColor: 'rgba(0, 0, 0, 0.3)' });

    let offset = 0;
    const limit = 50000; // 每次请求 5 万条
    let total = 0;
    let hasMore = true;

    try {
        while (hasMore) {
            const params = new URLSearchParams({
                market: market,
                interval: interval,
                symbol: symbol,
                range_type: rangeType,
                adj: adjType,
                bar_type: barType,
                offset: offset,
                limit: limit
            });
            
            if (threshold !== null) {
                params.append('bar_threshold', threshold);
            }

            const response = await fetch(`/api/kline/data?${params.toString()}`);
            const result = await response.json();
            
            if (result.detail) {
                throw new Error(result.detail);
            }

            if (!result.data || result.data.length === 0) {
                break;
            }

            // 更新总数
            if (total === 0 && result.total) {
                total = result.total;
            }

            // 拼接数据
            fullKlineData = fullKlineData.concat(result.data);

            // 更新进度
            const progress = total > 0 ? Math.round((fullKlineData.length / total) * 100) : 50;
            klineChart.hideLoading();
            klineChart.showLoading('default', { text: `正在加载数据 (${progress}%)...` });

            // 判断是否继续
            if (result.data.length < limit) {
                hasMore = false;
            } else {
                offset += limit;
                // 安全限制：防止前端内存爆掉，限制最大加载 100 万条
                if (offset >= 1000000) {
                    console.warn("Reached client-side limit of 1,000,000 candles.");
                    hasMore = false;
                    // 可选：提示用户
                }
            }
        }

        klineChart.hideLoading();
        
        if (fullKlineData.length === 0) {
             klineChart.setOption({ 
                title: { text: '无数据', subtext: '数据库中未找到记录', left: 'center', top: 'center' } 
            });
            return;
        }

        // 数据解析
        const dates = [];
        const ohlc = [];
        const volumes = [];
        const ticks = [];

        fullKlineData.forEach(item => {
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

        // 渲染图表
        renderChart(symbol, dates, ohlc, volumes, ticks, barType);

    } catch (e) {
        console.error("Load kline failed", e);
        alert("加载失败: " + e.message);
        if (klineChart) {
            klineChart.hideLoading();
            klineChart.clear();
            klineChart.setOption({ 
                title: { text: '加载错误', subtext: e.message, left: 'center', top: 'center' } 
            });
        }
    }
}

function renderChart(symbol, dates, ohlc, volumes, ticks, barType) {
    if (!klineChart) return;
    
    let series = [];
    let grids = [];
    let xAxes = [];
    let yAxes = [];
    
    // 性能优化配置
    const performanceOpts = {
        large: true,          // 开启大数据优化
        largeThreshold: 2000, // 超过 2000 条数据开启优化
        progressive: 1000,    // 渐进式渲染，每次渲染 1000 条
        progressiveThreshold: 5000, // 超过 5000 条开启渐进式
        animation: false      // 关闭动画，大幅提升性能
    };

    // 基础 K 线配置
    grids.push({ left: '10%', right: '8%', top: '10%', height: '50%' });
    xAxes.push({ 
        type: 'category', 
        data: dates, 
        boundaryGap: false, 
        axisLine: { onZero: false }, 
        splitLine: { show: false }, 
        min: 'dataMin', 
        max: 'dataMax' 
    });
    yAxes.push({ scale: true, splitArea: { show: true } });
    
    series.push({
        name: 'K线', 
        type: 'candlestick', 
        data: ohlc,
        ...performanceOpts, // 应用性能优化
        itemStyle: { color: '#ef5350', color0: '#26a69a', borderColor: '#ef5350', borderColor0: '#26a69a' }
    });

    // 底部指标配置
    if (barType === 'time') {
        grids.push({ left: '10%', right: '8%', top: '70%', height: '15%' });
        xAxes.push({ type: 'category', gridIndex: 1, data: dates, boundaryGap: false, axisLine: { onZero: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false }, min: 'dataMin', max: 'dataMax' });
        yAxes.push({ scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } });
        series.push({ 
            name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes, 
            ...performanceOpts, // 应用性能优化
            itemStyle: { color: '#26a69a' } 
        });
    } else {
        grids.push({ left: '10%', right: '8%', top: '70%', height: '15%' });
        xAxes.push({ type: 'category', gridIndex: 1, data: dates, boundaryGap: false, axisLine: { onZero: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false }, min: 'dataMin', max: 'dataMax' });
        yAxes.push({ scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } });
        
        series.push({ 
            name: '时间消耗', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: ticks, 
            ...performanceOpts, // 应用性能优化
            itemStyle: { color: '#5470c6' }
        });
    }

    const option = {
        title: { text: symbol.toUpperCase(), left: 'center' },
        tooltip: { 
            trigger: 'axis', 
            axisPointer: { type: 'cross' },
            backgroundColor: 'rgba(255, 255, 255, 0.9)',
            borderColor: '#eee',
            textStyle: { color: '#333' }
            // 注意：在大数据量下，tooltip 可能会慢，可以考虑 confine: true
        },
        legend: { data: ['K线', barType === 'time' ? '成交量' : '时间消耗'], bottom: 10 },
        grid: grids,
        xAxis: xAxes,
        yAxis: yAxes,
        dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1], start: 80, end: 100 }, // 默认显示最近 20%，避免初始渲染所有点
            { show: true, xAxisIndex: [0, 1], type: 'slider', bottom: '5%', start: 80, end: 100 }
        ],
        series: series
    };
    klineChart.setOption(option, true);
}