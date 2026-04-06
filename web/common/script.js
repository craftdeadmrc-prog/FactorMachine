// State
let currentTasks = {}; 
let selectedTaskNames = new Set();
let currentViewName = null;

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    switchView('dashboard', document.querySelector('.nav-item'));
});

// Navigation Router
async function switchView(viewName, navEl) {
    if (currentViewName) {
        const destroyFunc = window[`destroy_${currentViewName}`];
        if (typeof destroyFunc === 'function') {
            destroyFunc();
        }
    }

    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    if (navEl) navEl.classList.add('active');

    const titles = {
        'dashboard': '首页状态',
        'tasks': '任务执行',
        'logs': '日志查看',
        'kline': 'K线查看'
    };
    document.getElementById('page-title').innerText = titles[viewName] || viewName;

    const container = document.getElementById('view-container');
    container.innerHTML = '<div style="padding:20px; color:#999;">Loading...</div>';

    try {
        const htmlPath = `/${viewName}/index.html`;
        const res = await fetch(htmlPath);
        if (res.ok) {
            const html = await res.text();
            container.innerHTML = html;
            currentViewName = viewName;
            loadPageScript(viewName);
        } else {
            container.innerHTML = `<div style="color:red;">页面未找到: ${htmlPath}</div>`;
        }
    } catch (e) {
        console.error(e);
        container.innerHTML = `<div style="color:red;">加载失败: ${e.message}</div>`;
    }
}

function loadPageScript(viewName) {
    const existingScript = document.getElementById(`script-${viewName}`);
    if (existingScript) existingScript.remove();

    const script = document.createElement('script');
    script.src = `/${viewName}/script.js`;
    script.id = `script-${viewName}`;
    script.onload = () => {
        const initFunc = window[`init_${viewName}`];
        if (typeof initFunc === 'function') {
            initFunc();
        }
    };
    document.body.appendChild(script);
}

// API Wrappers
const API = {
    getTasks: async () => {
        const res = await fetch('/api/tasks');
        return await res.json();
    },
    getStatus: async () => {
        const res = await fetch('/api/status');
        return await res.json();
    },
    runTasks: async (payload) => {
        const res = await fetch('/api/run', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        return await res.json();
    },
    getLogs: async (taskName) => {
        const res = await fetch(`/api/logs/${taskName}`);
        return await res.json();
    },
    clearLogs: async (taskName) => {
        const res = await fetch(`/api/logs/${taskName}`, { method: 'DELETE' });
        return await res.json();
    },
    // Kline APIs
    getKlineTables: async (market) => {
        const res = await fetch(`/api/kline/tables/${market}`);
        return await res.json();
    },
    // 修复：补充获取代码列表的方法
    getKlineSymbols: async (market) => {
        const res = await fetch(`/api/kline/symbols/${market}`);
        return await res.json();
    },
    getKlineData: async (params) => {
        const query = new URLSearchParams(params).toString();
        const res = await fetch(`/api/kline/data?${query}`);
        return await res.json();
    }
};
