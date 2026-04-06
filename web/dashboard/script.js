// Dashboard Logic
// 将 timer 挂载到 window 防止模块重新加载时丢失引用，或使用全局管理
let dashboard_timer = null;

function init_dashboard() {
    // 立即更新一次
    updateStatus();
    // 启动定时器
    if (dashboard_timer) clearInterval(dashboard_timer);
    dashboard_timer = setInterval(updateStatus, 5000);
}

function destroy_dashboard() {
    // 视图切换时清理定时器，防止后台持续请求或内存泄漏
    if (dashboard_timer) {
        clearInterval(dashboard_timer);
        dashboard_timer = null;
    }
}

async function updateStatus() {
    try {
        const data = await API.getStatus();
        const grid = document.getElementById('status-grid');
        if (!grid) return; // 如果已经切换页面，元素不存在则直接退出
        
        grid.innerHTML = '';
        
        if (!data.tasks || data.tasks.length === 0) {
            grid.innerHTML = '<div style="color:#999; padding: 10px;">暂无任务状态</div>';
            return;
        }

        data.tasks.forEach(task => {
            const card = document.createElement('div');
            card.className = 'task-card';
            // 修复：确保颜色类名正确
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