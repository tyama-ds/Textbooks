/**
 * Agent of Agents - Frontend Application
 * Real-time pipeline visualization with SSE streaming.
 */

class AgentOfAgents {
    constructor() {
        this.sessionId = null;
        this.eventSource = null;
        this.events = [];
        this.fileContents = {};
        this.currentDetailTab = 'plan';
        this.currentFile = null;
        this.testOutputs = [];
        this.gitEntries = [];
        this.plan = null;
        this.isRunning = false;
        this.fixAttempts = 0;

        this.init();
    }

    init() {
        this.bindElements();
        this.bindEvents();
        this.updateModeBadge();
    }

    bindElements() {
        this.inputField = document.getElementById('task-input');
        this.runButton = document.getElementById('run-button');
        this.apiKeyInput = document.getElementById('api-key');
        this.modelSelect = document.getElementById('model-select');
        this.maxAttemptsInput = document.getElementById('max-attempts');
        this.modeBadge = document.getElementById('mode-badge');
        this.pipelineContainer = document.getElementById('pipeline-steps');
        this.detailContainer = document.getElementById('detail-content');
        this.detailTabs = document.querySelectorAll('.detail-tab');
    }

    bindEvents() {
        this.runButton.addEventListener('click', () => this.startPipeline());
        this.inputField.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.startPipeline();
            }
        });

        this.apiKeyInput.addEventListener('input', () => this.updateModeBadge());

        this.detailTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                this.detailTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                this.currentDetailTab = tab.dataset.tab;
                this.renderDetail();
            });
        });

        // Auto-resize textarea
        this.inputField.addEventListener('input', () => {
            this.inputField.style.height = 'auto';
            this.inputField.style.height = Math.min(this.inputField.scrollHeight, 200) + 'px';
        });
    }

    updateModeBadge() {
        const hasKey = this.apiKeyInput.value.trim().length > 0;
        this.modeBadge.className = 'mode-badge ' + (hasKey ? 'live' : 'demo');
        this.modeBadge.textContent = hasKey ? 'LIVE' : 'DEMO';
    }

    async startPipeline() {
        const request = this.inputField.value.trim();
        if (!request || this.isRunning) return;

        // Reset state
        this.events = [];
        this.fileContents = {};
        this.testOutputs = [];
        this.gitEntries = [];
        this.plan = null;
        this.fixAttempts = 0;
        this.pipelineContainer.innerHTML = '';
        this.isRunning = true;
        this.runButton.disabled = true;
        this.runButton.classList.add('running');
        this.runButton.textContent = 'Running...';

        try {
            // Start session
            const response = await fetch('/api/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    request: request,
                    api_key: this.apiKeyInput.value.trim(),
                    model: this.modelSelect.value,
                    max_attempts: parseInt(this.maxAttemptsInput.value) || 5,
                }),
            });

            const data = await response.json();
            if (data.error) {
                this.showError(data.error);
                return;
            }

            this.sessionId = data.session_id;

            // Connect to SSE stream
            this.connectSSE();

        } catch (err) {
            this.showError(`Connection error: ${err.message}`);
            this.stopPipeline();
        }
    }

    connectSSE() {
        if (this.eventSource) {
            this.eventSource.close();
        }

        this.eventSource = new EventSource(`/api/stream/${this.sessionId}`);

        this.eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleEvent(data);
            } catch (err) {
                console.error('Failed to parse event:', err);
            }
        };

        this.eventSource.onerror = () => {
            this.eventSource.close();
            this.stopPipeline();
        };
    }

    handleEvent(event) {
        this.events.push(event);

        switch (event.phase) {
            case 'init':
                this.addPipelineStep('init', 'Initialization', event, '\u25B6');
                break;
            case 'plan':
                if (event.status === 'start') {
                    this.addPipelineStep('plan', 'Planning Agent', event, '\u2726');
                } else {
                    this.updatePipelineStep('plan', event);
                    if (event.data.plan) {
                        this.plan = event.data.plan;
                        this.renderDetail();
                    }
                }
                break;
            case 'implement':
                if (event.status === 'start') {
                    this.addPipelineStep('implement', 'Implementation Agent', event, '\u2692');
                } else {
                    this.updatePipelineStep('implement', event);
                    if (event.data.file_contents) {
                        this.fileContents = event.data.file_contents;
                        if (!this.currentFile && event.data.files && event.data.files.length > 0) {
                            this.currentFile = event.data.files[0];
                        }
                        this.renderDetail();
                    }
                }
                break;
            case 'test':
                if (event.status === 'start') {
                    this.addPipelineStep(`test-${event.data.attempt || 1}`,
                        `Test Run #${event.data.attempt || 1}`, event, '\u2713');
                } else {
                    this.updatePipelineStep(`test-${event.data.attempt || 1}`, event);
                    if (event.data.output) {
                        this.testOutputs.push({
                            attempt: event.data.attempt || 1,
                            passed: event.status === 'success',
                            output: event.data.output,
                        });
                        this.renderDetail();
                    }
                }
                break;
            case 'fix':
                if (event.status === 'start') {
                    this.fixAttempts++;
                    this.addLoopIndicator();
                    this.addPipelineStep(`fix-${this.fixAttempts}`,
                        `Fix Agent #${this.fixAttempts}`, event, '\u2699');
                } else {
                    this.updatePipelineStep(`fix-${this.fixAttempts}`, event);
                    if (event.data.fixed_files) {
                        // Update file contents would require fetching
                        this.renderDetail();
                    }
                }
                break;
            case 'git':
                this.addPipelineStep(`git-${this.gitEntries.length}`, 'Git', event, '\u2191');
                this.gitEntries.push({
                    message: event.message,
                    action: event.data.action,
                    log: event.data.log,
                });
                this.renderDetail();
                break;
            case 'done':
                this.addPipelineStep('done', 'Complete', event, '\u2605');
                this.stopPipeline();
                break;
        }
    }

    addPipelineStep(id, title, event, icon) {
        // Add connector line (except for first step)
        if (this.pipelineContainer.children.length > 0) {
            const connector = document.createElement('div');
            connector.className = 'pipeline-connector active';
            this.pipelineContainer.appendChild(connector);
        }

        const step = document.createElement('div');
        step.className = `pipeline-step active`;
        step.id = `step-${id}`;
        step.dataset.phase = event.phase;

        const statusClass = event.status === 'start' ? 'running' :
            event.status === 'success' ? 'success' :
            event.status === 'error' ? 'error' : 'running';

        const statusText = event.status === 'start' ? 'RUNNING' :
            event.status === 'success' ? 'DONE' :
            event.status === 'error' ? 'FAILED' : event.status.toUpperCase();

        step.innerHTML = `
            <div class="step-header">
                <div class="step-icon ${event.phase}">${icon}</div>
                <span class="step-title">${title}</span>
                <span class="step-status ${statusClass}">
                    ${statusClass === 'running' ? '<span class="spinner"></span> ' : ''}${statusText}
                </span>
            </div>
            <div class="step-message">${this.escapeHtml(event.message)}</div>
        `;

        step.addEventListener('click', () => this.onStepClick(event));
        this.pipelineContainer.appendChild(step);
        step.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    updatePipelineStep(id, event) {
        const step = document.getElementById(`step-${id}`);
        if (!step) return;

        const statusClass = event.status === 'success' ? 'success' :
            event.status === 'error' ? 'error' : 'running';
        const statusText = event.status === 'success' ? 'DONE' :
            event.status === 'error' ? 'FAILED' : event.status.toUpperCase();

        step.className = `pipeline-step ${statusClass}`;

        const statusEl = step.querySelector('.step-status');
        if (statusEl) {
            statusEl.className = `step-status ${statusClass}`;
            statusEl.innerHTML = statusText;
        }

        const msgEl = step.querySelector('.step-message');
        if (msgEl) {
            msgEl.textContent = event.message;
        }
    }

    addLoopIndicator() {
        const indicator = document.createElement('div');
        indicator.className = 'loop-indicator';
        indicator.innerHTML = `
            <span>\u21BB</span>
            <span>Recursive Fix Loop</span>
            <span class="loop-count">#${this.fixAttempts}</span>
        `;
        // Add connector
        const connector = document.createElement('div');
        connector.className = 'pipeline-connector active';
        this.pipelineContainer.appendChild(connector);
        this.pipelineContainer.appendChild(indicator);
    }

    onStepClick(event) {
        // Switch detail tab based on phase
        const tabMap = {
            'plan': 'plan',
            'implement': 'code',
            'test': 'tests',
            'fix': 'code',
            'git': 'git',
        };
        const tab = tabMap[event.phase];
        if (tab) {
            this.currentDetailTab = tab;
            this.detailTabs.forEach(t => {
                t.classList.toggle('active', t.dataset.tab === tab);
            });
            this.renderDetail();
        }
    }

    renderDetail() {
        switch (this.currentDetailTab) {
            case 'plan':
                this.renderPlan();
                break;
            case 'code':
                this.renderCode();
                break;
            case 'tests':
                this.renderTests();
                break;
            case 'git':
                this.renderGit();
                break;
            case 'log':
                this.renderLog();
                break;
        }
    }

    renderPlan() {
        if (!this.plan) {
            this.detailContainer.innerHTML = `
                <div class="empty-state">
                    <div class="icon">\u2726</div>
                    <p>The planning agent will analyze your request and create a step-by-step implementation plan.</p>
                </div>
            `;
            return;
        }

        const steps = this.plan.steps || [];
        const files = this.plan.files_to_create || [];

        this.detailContainer.innerHTML = `
            <div class="plan-viewer">
                <div style="margin-bottom: 12px;">
                    <div style="font-size: 14px; font-weight: 600; color: var(--accent-cyan);">
                        ${this.escapeHtml(this.plan.project_name || 'Project')}
                    </div>
                    <div style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
                        ${this.escapeHtml(this.plan.description || '')}
                    </div>
                </div>
                <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin: 12px 0 8px;">
                    Implementation Steps
                </div>
                ${steps.map(s => `
                    <div class="plan-step">
                        <div class="plan-step-num">${s.step}</div>
                        <div class="plan-step-content">
                            <div class="plan-step-action">${this.escapeHtml(s.action)}</div>
                            <div class="plan-step-details">${this.escapeHtml(s.details)}</div>
                        </div>
                    </div>
                `).join('')}
                <div style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; margin: 16px 0 8px;">
                    Files to Create
                </div>
                ${files.map(f => `
                    <div style="display: flex; gap: 8px; padding: 4px 0; font-size: 12px;">
                        <span style="color: var(--accent-cyan);">${this.escapeHtml(f.path)}</span>
                        <span style="color: var(--text-muted);">\u2014 ${this.escapeHtml(f.purpose)}</span>
                    </div>
                `).join('')}
                <div style="margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--border); font-size: 12px;">
                    <span style="color: var(--text-muted);">Test command:</span>
                    <code style="color: var(--accent-green); margin-left: 4px;">${this.escapeHtml(this.plan.test_command || '')}</code>
                </div>
            </div>
        `;
    }

    renderCode() {
        const files = Object.keys(this.fileContents);
        if (files.length === 0) {
            this.detailContainer.innerHTML = `
                <div class="empty-state">
                    <div class="icon">\u2692</div>
                    <p>Generated code will appear here once the implementation agent completes its work.</p>
                </div>
            `;
            return;
        }

        if (!this.currentFile || !this.fileContents[this.currentFile]) {
            this.currentFile = files[0];
        }

        const content = this.fileContents[this.currentFile] || '';

        this.detailContainer.innerHTML = `
            <div class="file-tabs">
                ${files.map(f => `
                    <button class="file-tab ${f === this.currentFile ? 'active' : ''}"
                            onclick="app.selectFile('${this.escapeHtml(f)}')">${this.escapeHtml(f)}</button>
                `).join('')}
            </div>
            <div class="code-viewer">
                <div class="code-header">
                    <span class="code-filename">${this.escapeHtml(this.currentFile)}</span>
                    <span style="color: var(--text-muted); font-size: 11px;">
                        ${content.split('\n').length} lines
                    </span>
                </div>
                <pre class="code-content">${this.highlightCode(content)}</pre>
            </div>
        `;
    }

    selectFile(filename) {
        this.currentFile = filename;
        this.renderCode();
    }

    renderTests() {
        if (this.testOutputs.length === 0) {
            this.detailContainer.innerHTML = `
                <div class="empty-state">
                    <div class="icon">\u2713</div>
                    <p>Test results will appear here once the testing phase begins.</p>
                </div>
            `;
            return;
        }

        this.detailContainer.innerHTML = this.testOutputs.map((t, i) => `
            <div style="margin-bottom: 12px;">
                <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px;">
                    <span style="font-size: 13px; font-weight: 600;">Test Run #${t.attempt}</span>
                    <span class="step-status ${t.passed ? 'success' : 'error'}">
                        ${t.passed ? 'PASSED' : 'FAILED'}
                    </span>
                </div>
                <div class="test-output">${this.colorizeTestOutput(t.output)}</div>
            </div>
        `).join('');
    }

    renderGit() {
        if (this.gitEntries.length === 0) {
            this.detailContainer.innerHTML = `
                <div class="empty-state">
                    <div class="icon">\u2191</div>
                    <p>Git history will appear here once commits are made.</p>
                </div>
            `;
            return;
        }

        this.detailContainer.innerHTML = `
            <div class="git-log">
                ${this.gitEntries.map(g => `
                    <div class="git-entry">
                        <span class="git-hash">\u25CF</span>
                        <span class="git-message">${this.escapeHtml(g.message)}</span>
                    </div>
                `).join('')}
                ${this.gitEntries[this.gitEntries.length - 1].log ? `
                    <div style="margin-top: 12px; padding-top: 8px; border-top: 1px solid var(--border);">
                        <div style="font-size: 11px; color: var(--text-muted); margin-bottom: 6px;">GIT LOG</div>
                        <pre style="font-size: 12px; color: var(--text-secondary); white-space: pre-wrap;">${
                            this.escapeHtml(this.gitEntries[this.gitEntries.length - 1].log)
                        }</pre>
                    </div>
                ` : ''}
            </div>
        `;
    }

    renderLog() {
        this.detailContainer.innerHTML = `
            <div class="json-viewer"><pre>${
                this.events.map(e =>
                    `<span class="json-key">[${e.phase}]</span> <span class="${
                        e.status === 'success' ? 'json-string' :
                        e.status === 'error' ? 'json-bool' : 'json-number'
                    }">${e.status}</span> ${this.escapeHtml(e.message)}`
                ).join('\n')
            }</pre></div>
        `;
    }

    stopPipeline() {
        this.isRunning = false;
        this.runButton.disabled = false;
        this.runButton.classList.remove('running');
        this.runButton.textContent = 'Build It';
        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }
    }

    showError(message) {
        this.pipelineContainer.innerHTML = `
            <div class="pipeline-step error">
                <div class="step-header">
                    <div class="step-icon fix">\u2716</div>
                    <span class="step-title">Error</span>
                    <span class="step-status error">FAILED</span>
                </div>
                <div class="step-message">${this.escapeHtml(message)}</div>
            </div>
        `;
        this.stopPipeline();
    }

    highlightCode(code) {
        // Simple syntax highlighting
        return this.escapeHtml(code)
            .replace(/(#.*$)/gm, '<span style="color: var(--text-muted);">$1</span>')
            .replace(/("""[\s\S]*?""")/g, '<span style="color: var(--accent-green);">$1</span>')
            .replace(/\b(def|class|import|from|return|if|else|elif|for|while|try|except|raise|with|as|not|and|or|in|is|True|False|None)\b/g,
                '<span style="color: var(--accent-purple);">$1</span>')
            .replace(/\b(self)\b/g, '<span style="color: var(--accent-orange);">$1</span>')
            .replace(/(\"[^\"]*\")/g, '<span style="color: var(--accent-green);">$1</span>')
            .replace(/(\'[^\']*\')/g, '<span style="color: var(--accent-green);">$1</span>');
    }

    colorizeTestOutput(output) {
        return this.escapeHtml(output)
            .replace(/(PASSED|passed|ok)/gi, '<span class="pass">$1</span>')
            .replace(/(FAILED|failed|ERROR|error|ERRORS)/gi, '<span class="fail">$1</span>');
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }
}

// Initialize app
let app;
document.addEventListener('DOMContentLoaded', () => {
    app = new AgentOfAgents();
});
