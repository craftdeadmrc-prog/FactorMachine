// web/dashboard/script.js
// Dashboard Logic - Pure WebSocket
let dashboard_timer = null;

function init_dashboard() {
    updateStatus();
    if (dashboard_timer) clearInterval(dashboard_timer);
    dashboard_timer = setInterval(updateStatus, 5000);
}

function destroy_dashboard() {
    if (dashboard_timer) {
        clearInterval(dashboard_timer);
        dashboard_timer = null;
    }
}

async function updateStatus() {
    try {
        // 纯WS传输，移除useWS参数
        const data = await WSAPI.call('status.get');
        const grid = document.getElementById('status-grid');
        if (!grid) return;
        
        grid.innerHTML = '';
        
        if (!data.tasks || data.tasks.length === 0) {
            grid.innerHTML = '<div style="color:#999; padding: 10px;">暂无任务状态</div>';
            return;
        }

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
        if (scheduleList) {
            scheduleList.innerHTML = '';
            if (!data.schedules || data.schedules.length === 0) {
                scheduleList.innerHTML = '<div style="color:#999">无定时任务</div>';
            } else {
                data.schedules.forEach(sch => {
                    const item = document.createElement('div');
                    item.style.padding = '8px 0';
                    item.style.borderBottom = '1px solid #eee';
                    item.innerHTML = `
                        <div style="font-size:14px; word-break: break-all;">${sch.id}</div>
                        <div style="font-size:12px; color:#999">${sch.next_run_time || 'N/A'}</div>
                    `;
                    scheduleList.appendChild(item);
                });
            }
        }
    } catch (e) {
        console.error('Status update failed:', e);
    }
}
