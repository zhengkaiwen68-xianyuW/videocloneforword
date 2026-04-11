<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>人格深度重构与洗稿引擎</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: "Microsoft YaHei", Arial, sans-serif; background: #1a1a2e; color: #eee; height: 100vh; }
        .container { display: flex; height: 100vh; }

        /* Left Column - Author Library */
        .left-col { width: 280px; background: #16213e; padding: 20px; overflow-y: auto; border-right: 1px solid #0f3460; }
        .left-col h2 { font-size: 16px; margin-bottom: 15px; color: #e94560; }
        .author-list { list-style: none; }
        .author-item { background: #1a1a2e; padding: 12px; margin-bottom: 8px; border-radius: 6px; cursor: pointer; transition: all 0.2s; }
        .author-item:hover { background: #0f3460; }
        .author-item.selected { border: 2px solid #e94560; }
        .author-item h3 { font-size: 14px; margin-bottom: 4px; }
        .author-item p { font-size: 11px; color: #888; }
        .author-item .verbal-tics { font-size: 11px; color: #4ecca3; margin-top: 4px; }
        .add-author-btn { width: 100%; padding: 10px; background: #e94560; border: none; border-radius: 6px; color: white; cursor: pointer; margin-top: 10px; }

        /* Middle Column - Processing */
        .middle-col { flex: 1; padding: 20px; display: flex; flex-direction: column; }
        .middle-col h1 { font-size: 20px; margin-bottom: 15px; color: #e94560; }
        .source-input { width: 100%; height: 200px; background: #16213e; border: 1px solid #0f3460; border-radius: 8px; padding: 15px; color: #eee; font-size: 14px; resize: none; margin-bottom: 15px; }
        .source-input:focus { outline: none; border-color: #e94560; }
        .controls { display: flex; gap: 10px; margin-bottom: 15px; }
        .controls select { flex: 1; padding: 10px; background: #16213e; border: 1px solid #0f3460; border-radius: 6px; color: #eee; }
        .controls input { flex: 1; padding: 10px; background: #16213e; border: 1px solid #0f3460; border-radius: 6px; color: #eee; }
        .generate-btn { padding: 12px 30px; background: linear-gradient(135deg, #e94560, #0f3460); border: none; border-radius: 6px; color: white; cursor: pointer; font-size: 14px; }
        .generate-btn:hover { opacity: 0.9; }
        .generate-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .progress { margin-top: 10px; display: none; }
        .progress-bar { height: 4px; background: #0f3460; border-radius: 2px; overflow: hidden; }
        .progress-fill { height: 100%; background: #e94560; width: 0%; transition: width 0.3s; }
        .progress-text { font-size: 12px; color: #888; margin-top: 5px; }

        /* Right Column - Results */
        .right-col { width: 350px; background: #16213e; padding: 20px; overflow-y: auto; border-left: 1px solid #0f3460; }
        .right-col h2 { font-size: 16px; margin-bottom: 15px; color: #e94560; }
        .result-box { background: #1a1a2e; border-radius: 8px; padding: 15px; margin-bottom: 15px; min-height: 150px; }
        .result-box p { font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
        .score-display { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
        .score { font-size: 24px; color: #4ecca3; font-weight: bold; }
        .score-label { font-size: 12px; color: #888; }
        .copy-btn, .download-btn { padding: 8px 15px; background: #0f3460; border: none; border-radius: 4px; color: #eee; cursor: pointer; font-size: 12px; margin-right: 5px; }
        .copy-btn:hover, .download-btn:hover { background: #e94560; }

        /* Modal */
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 100; }
        .modal.active { display: flex; justify-content: center; align-items: center; }
        .modal-content { background: #16213e; padding: 25px; border-radius: 10px; width: 400px; max-width: 90%; }
        .modal-content h2 { margin-bottom: 15px; color: #e94560; }
        .modal-content input, .modal-content textarea { width: 100%; padding: 10px; background: #1a1a2e; border: 1px solid #0f3460; border-radius: 6px; color: #eee; margin-bottom: 10px; }
        .modal-content textarea { height: 150px; resize: none; }
        .modal-content .btn-group { display: flex; gap: 10px; margin-top: 15px; }
        .modal-content button { flex: 1; padding: 10px; border: none; border-radius: 6px; cursor: pointer; }
        .modal-content .cancel-btn { background: #333; color: #eee; }
        .modal-content .confirm-btn { background: #e94560; color: white; }

        /* Toast */
        .toast { position: fixed; bottom: 20px; right: 20px; background: #4ecca3; color: #1a1a2e; padding: 12px 20px; border-radius: 6px; display: none; z-index: 200; }
    </style>
</head>
<body>
    <div class="container">
        <!-- Left Column - Author Library -->
        <div class="left-col">
            <h2>作者人格库</h2>
            <ul class="author-list" id="authorList"></ul>
            <button class="add-author-btn" onclick="openAddModal()">+ 新建人格</button>
        </div>

        <!-- Middle Column - Processing -->
        <div class="middle-col">
            <h1>短视频人格深度重构引擎</h1>
            <textarea class="source-input" id="sourceText" placeholder="输入原始素材文案..."></textarea>
            <div class="controls">
                <select id="authorSelect">
                    <option value="">选择作者人格</option>
                </select>
                <input type="text" id="lockedTerms" placeholder="术语锚点（用逗号分隔）">
            </div>
            <button class="generate-btn" id="generateBtn" onclick="generate()">开始重写</button>
            <div class="progress" id="progress">
                <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
                <p class="progress-text" id="progressText">准备中...</p>
            </div>
        </div>

        <!-- Right Column - Results -->
        <div class="right-col">
            <h2>生成结果</h2>
            <div class="score-display">
                <div><span class="score" id="scoreValue">--</span><br><span class="score-label">一致性评分</span></div>
                <div>
                    <button class="copy-btn" onclick="copyResult()">复制</button>
                    <button class="download-btn" onclick="downloadResult()">下载</button>
                </div>
            </div>
            <div class="result-box">
                <p id="resultText">生成的文案将显示在这里...</p>
            </div>
        </div>
    </div>

    <!-- Add Author Modal -->
    <div class="modal" id="addModal">
        <div class="modal-content">
            <h2>新建人格画像</h2>
            <input type="text" id="authorName" placeholder="作者名称">
            <textarea id="sourceTexts" placeholder="输入 ASR 原文（多篇用空行分隔，至少3篇）"></textarea>
            <div class="btn-group">
                <button class="cancel-btn" onclick="closeAddModal()">取消</button>
                <button class="confirm-btn" onclick="createAuthor()">创建</button>
            </div>
        </div>
    </div>

    <!-- Toast -->
    <div class="toast" id="toast">操作成功</div>

    <script>
        let authors = [];
        let selectedAuthorId = null;
        let currentResult = '';

        // Load authors on page load
        document.addEventListener('DOMContentLoaded', loadAuthors);

        async function loadAuthors() {
            try {
                const resp = await fetch('/v1/personas');
                const data = await resp.json();
                authors = data.personas || [];
                renderAuthorList();
                updateAuthorSelect();
            } catch (e) {
                console.error('Failed to load authors:', e);
            }
        }

        function renderAuthorList() {
            const list = document.getElementById('authorList');
            list.innerHTML = authors.map(a => `
                <li class="author-item ${a.id === selectedAuthorId ? 'selected' : ''}" onclick="selectAuthor('${a.id}')">
                    <h3>${a.name}</h3>
                    <p>创建于 ${new Date(a.created_at).toLocaleDateString()}</p>
                    <p class="verbal-tics">${a.verbal_tics.slice(0,3).join(', ') || '暂无口头禅'}</p>
                </li>
            `).join('');
        }

        function updateAuthorSelect() {
            const select = document.getElementById('authorSelect');
            select.innerHTML = '<option value="">选择作者人格</option>' +
                authors.map(a => `<option value="${a.id}">${a.name}</option>`).join('');
        }

        function selectAuthor(id) {
            selectedAuthorId = id;
            document.getElementById('authorSelect').value = id;
            renderAuthorList();
        }

        function openAddModal() {
            document.getElementById('addModal').classList.add('active');
        }

        function closeAddModal() {
            document.getElementById('addModal').classList.remove('active');
            document.getElementById('authorName').value = '';
            document.getElementById('sourceTexts').value = '';
        }

        async function createAuthor() {
            const name = document.getElementById('authorName').value.trim();
            const texts = document.getElementById('sourceTexts').value.split('\n\n').filter(t => t.trim());

            if (!name || texts.length < 1) {
                showToast('请填写作者名称和至少1篇文案');
                return;
            }

            try {
                const resp = await fetch('/v1/personas', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, source_texts: texts })
                });
                const data = await resp.json();
                if (data.id) {
                    showToast('人格创建成功');
                    closeAddModal();
                    loadAuthors();
                } else {
                    showToast('创建失败: ' + (data.detail?.message || '未知错误'));
                }
            } catch (e) {
                showToast('创建失败: ' + e.message);
            }
        }

        async function generate() {
            const sourceText = document.getElementById('sourceText').value.trim();
            const authorId = document.getElementById('authorSelect').value;

            if (!sourceText) { showToast('请输入原始素材'); return; }
            if (!authorId) { showToast('请选择作者人格'); return; }

            const btn = document.getElementById('generateBtn');
            const progress = document.getElementById('progress');

            btn.disabled = true;
            progress.style.display = 'block';
            document.getElementById('progressText').textContent = '正在提交任务...';

            try {
                // Submit batch rewrite task
                const resp = await fetch('/v1/process/batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        source_texts: [sourceText],
                        persona_ids: [authorId],
                        locked_terms: document.getElementById('lockedTerms').value.split(',').map(t => t.trim()).filter(t => t)
                    })
                });
                const data = await resp.json();

                if (data.task_ids && data.task_ids.length > 0) {
                    pollTaskStatus(data.task_ids[0]);
                } else {
                    showToast('提交失败');
                    btn.disabled = false;
                    progress.style.display = 'none';
                }
            } catch (e) {
                showToast('提交失败: ' + e.message);
                btn.disabled = false;
                progress.style.display = 'none';
            }
        }

        async function pollTaskStatus(taskId) {
            const progressText = document.getElementById('progressText');
            const progressFill = document.getElementById('progressFill');

            const check = async () => {
                try {
                    const resp = await fetch(`/v1/tasks/${taskId}/status`);
                    const data = await resp.json();

                    progressText.textContent = `迭代 ${data.iteration}/5 | 得分: ${data.current_score}`;
                    progressFill.style.width = `${(data.iteration / 5) * 100}%`;

                    if (data.status === 'completed' || data.status === 'completed_below_threshold') {
                        currentResult = data.best_text;
                        document.getElementById('resultText').textContent = currentResult;
                        document.getElementById('scoreValue').textContent = data.best_score.toFixed(1);
                        document.getElementById('generateBtn').disabled = false;
                        document.getElementById('progress').style.display = 'none';
                        showToast('生成完成');
                    } else if (data.status === 'failed') {
                        showToast('生成失败');
                        document.getElementById('generateBtn').disabled = false;
                        document.getElementById('progress').style.display = 'none';
                    } else {
                        setTimeout(check, 2000);
                    }
                } catch (e) {
                    setTimeout(check, 2000);
                }
            };

            check();
        }

        function copyResult() {
            if (currentResult) {
                navigator.clipboard.writeText(currentResult);
                showToast('已复制到剪贴板');
            }
        }

        function downloadResult() {
            if (!currentResult) return;
            const blob = new Blob([currentResult], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'rewritten_text.txt';
            a.click();
            URL.revokeObjectURL(url);
        }

        function showToast(msg) {
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.style.display = 'block';
            setTimeout(() => toast.style.display = 'none', 3000);
        }
    </script>
</body>
</html>
