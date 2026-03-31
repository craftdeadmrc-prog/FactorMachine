// State
let currentTasks = {}; // 存储任务结构以便快速查找
let selectedTaskNames = new Set();
let statusInterval = null;
// Initialization
document.addEventListener('DOMContentLoaded', () => {
    loadTasks();
    startStatusPolling();
});
// Navigation
function switchView(viewName, navEl) {
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    navEl.classList.add('active');
    document.getElementById('view-dashboard').classList.add('hidden');
    document.getElementById('view-tasks').classList.add('hidden');
    document.getElementById('view-logs').classList.add('hidden');
    document.getElementById(`view-${viewName}`).classList.remove('hidden');
    const titles = {
        'dashboard': '首页状态',
        'tasks': '任务执行',
        'logs': '日志查看'
    };
    document.getElementById('page-title').innerText = titles[viewName];
    if (viewName === 'logs') loadLogsList();
}
// API: Load Tasks for Selection
async function loadTasks() {
    try {
        const res = await fetch('/api/tasks');
        const data = await res.json();
        const container = document.getElementById('task-selection-list');
        // 保留控制按钮，清空其他
        const controls = container.querySelector('.list-controls');
        container.innerHTML = '';
        container.appendChild(controls);
        currentTasks = {}; // 重置缓存
        // 定义渲染顺序
        const groupOrder = ["System", "ashare", "fund", "crypto"];
        const allGroups = Object.keys(data);
        allGroups.sort((a, b) => {
            const idxA = groupOrder.indexOf(a);
            const idxB = groupOrder.indexOf(b);
            if (idxA === -1 && idxB === -1) return a.localeCompare(b);
            if (idxA === -1) return 1;
            if (idxB === -1) return -1;
            return idxA - idxB;
        });
        for (const groupName of allGroups) {
            const group = document.createElement('div');
            group.className = 'folder-group';
            const title = document.createElement('div');
            title.className = 'folder-title';
            title.innerText = groupName === "System" ? "系统任务" : groupName.toUpperCase();
            group.appendChild(title);
            const tasks = data[groupName];
            tasks.forEach(task => {
                currentTasks[task.name] = task; 
                const item = document.createElement('div');
                item.className = 'task-item';
                item.dataset.name = task.name;
                item.onclick = (e) => toggleSelection(task.name, item);
                item.innerHTML = `
                    <div style="display:flex; align-items:center; overflow:hidden;">
                        <span class="task-item-icon">○</span>
                        <span style="font-weight:500;">${task.name}</span>
                    </div>
                    <small style="color:#888; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width: 100px;">${task.description}</small>
                `;
                group.appendChild(item);
            });
            container.appendChild(group);
        }
    } catch (e) {
        console.error('Failed to load tasks:', e);
    }
}
// Selection Logic
function toggleSelection(taskName, itemElement) {
    if (selectedTaskNames.has(taskName)) {
        selectedTaskNames.delete(taskName);
        itemElement.classList.remove('selected');
        itemElement.querySelector('.task-item-icon').innerText = '○';
    } else {
        selectedTaskNames.add(taskName);
        itemElement.classList.add('selected');
        itemElement.querySelector('.task-item-icon').innerText = '●';
    }
}
function selectAllTasks() {
    document.querySelectorAll('.task-item').forEach(item => {
        const name = item.dataset.name;
        if (!selectedTaskNames.has(name)) {
            selectedTaskNames.add(name);
            item.classList.add('selected');
            item.querySelector('.task-item-icon').innerText = '●';
        }
    });
}
function clearSelection() {
    selectedTaskNames.clear();
    document.querySelectorAll('.task-item').forEach(item => {
        item.classList.remove('selected');
        item.querySelector('.task-item-icon').innerText = '○';
    });
}
// API: Status Polling
function startStatusPolling() {
    updateStatus();
    statusInterval = setInterval(updateStatus, 5000);
}
async function updateStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        const grid = document.getElementById('status-grid');
        grid.innerHTML = '';
        data.tasks.forEach(task => {
            const card = document.createElement('div');
            card.className = 'task-card';
            const colorClass = `status-${task.color}`; 
            card.innerHTML = `
                <div class="task-info">
                    <span class="status-dot ${colorClass}"></span>
                    <span class="task-name" title="${task.name}">${task.name}</span>
                </div>
                <div style="font-size:12px; color:#888; white-space:nowrap; margin-left:8px;">${task.status}</div>
            `;
            grid.appendChild(card);
        });
        const scheduleList = document.getElementById('schedule-list');
        scheduleList.innerHTML = '';
        if (data.schedules.length === 0) {
            scheduleList.innerHTML = '<div style="color:#999">无定时任务</div>';
        } else {
            data.schedules.forEach(sch => {
                const item = document.createElement('div');
                item.style.padding = '8px 0';
                item.style.borderBottom = '1px solid #eee';
                item.innerHTML = `
                    <div style="font-size:14px; word-break: break-all;">${sch.id}</div>
                    <div style="font-size:12px; color:#999">${sch.next_run_time}</div>
                `;
                scheduleList.appendChild(item);
            });
        }
    } catch (e) {
        console.error('Status update failed:', e);
    }
}
// Logic: Run Task
async function submitExecution() {
    if (selectedTaskNames.size === 0) {
        alert('请至少选择一个任务');
        return;
    }
    const taskNames = Array.from(selectedTaskNames);
    const symbolsRaw = document.getElementById('exec-symbols').value;
    const startDate = document.getElementById('exec-start-date').value || null;
    const endDate = document.getElementById('exec-end-date').value || null;
    const update = document.getElementById('exec-update').checked;
    const symbols = symbolsRaw.split(/[\n,]+/).map(s => s.trim()).filter(s => s);
    const payload = {
        task_names: taskNames,
        symbols: symbols, 
        start_date: startDate,
        end_date: endDate,
        update: update
    };
    try {
        const res = await fetch('/api/run', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        const result = await res.json();
        if (res.ok) {
            alert(result.message);
            // 切换到首页查看状态
            document.querySelector('.nav-item').click(); 
        } else {
            alert('执行失败: ' + (result.detail || JSON.stringify(result)));
        }
    } catch (e) {
        alert('执行失败: ' + e.message);
    }
}
// Logic: Logs
async function loadLogsList() {
    try {
        const res = await fetch('/api/tasks');
        const data = await res.json();
        const container = document.getElementById('log-list-container');
        container.innerHTML = '';
        const allTasks = [];
        Object.values(data).forEach(arr => allTasks.push(...arr));
        allTasks.forEach(task => {
            const item = document.createElement('div');
            item.className = 'log-item';
            item.innerHTML = `
                <span>${task.name}</span>
                <div class="log-actions">
                    <button class="btn-danger" onclick="event.stopPropagation(); clearLogs('${task.name}')">清理日志</button>
                    <span style="color:#999">></span>
                </div>
            `;
            item.onclick = () => loadLogDetail(task.name, item);
            container.appendChild(item);
        });
    } catch (e) {
        console.error(e);
    }
}
async function clearLogs(taskName) {
    if(!confirm(`确定要清理任务 [${taskName}] 的所有日志吗？此操作不可恢复。`)) {
        return;
    }
    try {
        const res = await fetch(`/api/logs/${taskName}`, {
            method: 'DELETE'
        });
        if (res.ok) {
            alert('日志清理成功');
            document.getElementById('log-detail-view').innerText = '';
            document.getElementById('log-detail-view').classList.remove('open');
        } else {
            const data = await res.json();
            alert('清理失败: ' + (data.detail || '未知错误'));
        }
    } catch (e) {
        alert('清理失败: ' + e.message);
    }
}
async function loadLogDetail(taskName, itemElement) {
    const detail = document.getElementById('log-detail-view');
    detail.classList.add('open');
    detail.innerText = 'Loading...';
    try {
        const res = await fetch(`/api/logs/${taskName}`);
        const data = await res.json();
        if (data.logs && data.logs.length > 0) {
            const text = data.logs.map(log => 
                `[${log.date}] [${log.level}] ${log.message}`
            ).reverse().join('\n');
            detail.innerText = text;
        } else if (data.error) {
            detail.innerText = `Info: ${data.error}`;
        } else {
            detail.innerText = 'No logs found.';
        }
    } catch (e) {
        detail.innerText = 'Failed to fetch logs.';
    }
}