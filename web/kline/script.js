// Kline Logic
let klineChart = null;

// 数据缓存与状态
let allOverviewData = []; // 缓存所有概览数据
let renderedCount = 0;
const PAGE_SIZE = 100;
let currentSortKey = 'symbol';
let currentSymbol = '';

function init_kline() {
    const chartDom = document.getElementById('kline-chart-area');
    if (chartDom && typeof echarts !== 'undefined') {
        klineChart = echarts.init(chartDom);
        window.addEventListener('resize', () => klineChart && klineChart.resize());
    }
    populateMarkets();
    
    // 绑定滚动加载事件
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
    // 重置状态
    allOverviewData = [];
    renderedCount = 0;
}

async function populateMarkets() {
    try {
        const data = await API.getTasks();
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

    // 重置
    intervalSelect.innerHTML = '<option value="">加载中...</option>';
    intervalSelect.disabled = true;
    symbolInput.disabled = true;
    loadBtn.disabled = true;
    symbolInput.value = '';
    symbolList.innerHTML = '';
    
    // 清空概览
    allOverviewData = [];
    renderedCount = 0;
    document.getElementById('symbol-grid-container').innerHTML = '';

    if (!market) return;

    try {
        // 1. 获取 K线表
        const tables = await API.getKlineTables(market);
        intervalSelect.innerHTML = '';
        
        // 增加类型检查，防止后端返回非数组时报错
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

        // 2. 获取代码列表 (修复：补全缺失的代码行)
        const symbols = await API.getKlineSymbols(market);
        
        if (symbols && symbols.length > 0) {
            symbols.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s;
                symbolList.appendChild(opt);
            });
        }

        // 3. 自动加载第一个周期的概览数据
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

    try {
        // 调用新接口获取概览数据
        const data = await fetch(`/api/kline/overview?market=${market}&interval=${interval}`).then(res => res.json());
        
        allOverviewData = data || [];
        // 排序
        sortSymbols(currentSortKey, null, false); // false 表示不重新请求，仅重排
        
    } catch (e) {
        console.error("Load overview failed", e);
    }
}

// 排序逻辑
function sortSymbols(key, btnElement, needReload = true) {
    currentSortKey = key;
    
    // 更新按钮样式
    if (btnElement) {
        document.querySelectorAll('.symbol-list-controls .btn-xs').forEach(b => b.classList.remove('active'));
        btnElement.classList.add('active');
    }

    // 全局排序
    if (key === 'pct_change') {
        allOverviewData.sort((a, b) => (b.pct_change || 0) - (a.pct_change || 0)); // 降序
    } else {
        allOverviewData.sort((a, b) => (a.symbol || '').localeCompare(b.symbol || '')); // 升序
    }

    // 重新渲染
    renderedCount = 0;
    document.getElementById('symbol-grid-container').innerHTML = '';
    loadMoreSymbols();
}

// 分批渲染
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

        const pct = item.pct_change || 0;
        const isUp = pct >= 0;
        const colorClass = isUp ? 'up' : 'down';
        const bgClass = isUp ? 'bg-up' : 'bg-down';

        card.innerHTML = `
            <div class="name" title="${item.short_name || ''}">${item.short_name || '-'}</div>
            <div class="code">${item.symbol}</div>
            <div class="price-info">
                <span class="price ${colorClass}">${item.close ? item.close.toFixed(2) : '-'}</span>
                <span class="pct ${bgClass} ${colorClass}">${isUp ? '+' : ''}${pct.toFixed(2)}%</span>
            </div>
        `;
        
        card.onclick = () => {
            currentSymbol = item.symbol;
            // 更新选中样式
            container.querySelectorAll('.symbol-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            // 更新手动输入框
            document.getElementById('kline-symbol-manual').value = item.symbol;
            // 加载K线
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

async function loadKline(symbol) {
    if(!symbol) return;
    
    const market = document.getElementById('kline-market').value;
    const interval = document.getElementById('kline-interval').value;
    const rangeType = document.getElementById('kline-range').value;

    if (!market || !interval) return;

    if (klineChart) klineChart.showLoading();

    try {
        const rawData = await API.getKlineData({
            market: market,
            interval: interval,
            symbol: symbol,
            range_type: rangeType
        });

        if (!rawData || rawData.length === 0) {
            if (klineChart) {
                klineChart.hideLoading();
                klineChart.clear();
                klineChart.setOption({ title: { text: '无数据', left: 'center', top: 'center' } });
            }
            return;
        }

        const dates = [];
        const ohlc = [];
        const volumes = [];

        rawData.forEach(item => {
            dates.push(item.date);
            ohlc.push([
                parseFloat(item.open),
                parseFloat(item.close),
                parseFloat(item.low), // SQL已映射
                parseFloat(item.high)  // SQL已映射
            ]);
            volumes.push(parseFloat(item.volume || 0));
        });

        renderChart(symbol, dates, ohlc, volumes);

    } catch (e) {
        console.error("Load kline failed", e);
        alert("加载失败: " + e.message);
    } finally {
        if (klineChart) klineChart.hideLoading();
    }
}

function renderChart(symbol, dates, ohlc, volumes) {
    if (!klineChart) return;

    const option = {
        title: { text: symbol.toUpperCase(), left: 'center' },
        tooltip: { 
            trigger: 'axis', 
            axisPointer: { type: 'cross' },
            backgroundColor: 'rgba(255, 255, 255, 0.9)',
            borderColor: '#eee',
            textStyle: { color: '#333' }
        },
        legend: { data: ['K线', '成交量'], bottom: 10 },
        grid: [
            { left: '10%', right: '8%', top: '10%', height: '50%' },
            { left: '10%', right: '8%', top: '70%', height: '15%' }
        ],
        xAxis: [
            { type: 'category', data: dates, boundaryGap: false, axisLine: { onZero: false }, splitLine: { show: false }, min: 'dataMin', max: 'dataMax' },
            { type: 'category', gridIndex: 1, data: dates, boundaryGap: false, axisLine: { onZero: false }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false }, min: 'dataMin', max: 'dataMax' }
        ],
        yAxis: [
            { scale: true, splitArea: { show: true } },
            { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } }
        ],
        dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1], start: 50, end: 100 },
            { show: true, xAxisIndex: [0, 1], type: 'slider', bottom: '5%', start: 50, end: 100 }
        ],
        series: [
            {
                name: 'K线', type: 'candlestick', data: ohlc,
                itemStyle: { color: '#ef5350', color0: '#26a69a', borderColor: '#ef5350', borderColor0: '#26a69a' }
            },
            { 
                name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1, data: volumes, 
                itemStyle: { color: '#26a69a' } 
            }
        ]
    };
    klineChart.setOption(option, true);
}