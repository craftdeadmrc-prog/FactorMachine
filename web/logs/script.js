// web/logs/script.js
// Logs Logic - Pure WebSocket, filter undefined tasks
function init_logs() {
    loadLogsList();
}

async function loadLogsList() {
    try {
        const data = await WSAPI.get('/tasks');
        const container = document.getElementById('log-list-container');
        container.innerHTML = '';
        
        const allTasks = [];
        Object.values(data).forEach(arr => {
            if (Array.isArray(arr)) {
                arr.forEach(task => {
                    if (task && task.name && typeof task.name === 'string') {
                        allTasks.push(task);
                    }
                });
            }
        });
        
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
    if(!confirm(`确定要清理任务 [${taskName}] 的所有日志吗？此操作不可恢复。`)) return;
    
    try {
        const data = await WSAPI.delete('/logs/' + encodeURIComponent(taskName));
        alert('日志清理成功');
        const detail = document.getElementById('log-detail-view');
        if (detail) {
            detail.innerText = '';
            detail.classList.remove('open');
        }
    } catch (e) {
        alert('清理失败: ' + e.message);
    }
}

async function loadLogDetail(taskName, itemElement) {
    const detail = document.getElementById('log-detail-view');
    if (!detail) return;
    detail.classList.add('open');
    detail.innerText = 'Loading...';
    try {
        const data = await WSAPI.get('/logs/' + encodeURIComponent(taskName));
        if (data.logs && Array.isArray(data.logs) && data.logs.length > 0) {
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