// Tasks Logic
function init_tasks() {
    loadTasks();
}

async function loadTasks() {
    try {
        const data = await API.getTasks();
        const container = document.getElementById('task-selection-list');
        const controls = container.querySelector('.list-controls');
        container.innerHTML = '';
        container.appendChild(controls);
        
        // 重置全局状态
        currentTasks = {}; 
        
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
        const result = await API.runTasks(payload);
        alert(result.message || JSON.stringify(result));
        // 切换首页
        switchView('dashboard', document.querySelector('.nav-item'));
    } catch (e) {
        alert('执行失败: ' + e.message);
    }
}