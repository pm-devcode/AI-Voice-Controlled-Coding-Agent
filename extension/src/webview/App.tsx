import React, { useState, useEffect, useRef } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import hljs from 'highlight.js';
import { WebSocketClient, Message } from './services/websocket';

const vscode = (window as any).acquireVsCodeApi();

// Configure marked options with highlight.js
marked.setOptions({
    breaks: true,
    gfm: true,
    highlight: function(code: string, lang: string) {
        if (lang && hljs.getLanguage(lang)) {
            try {
                return (hljs as any).highlight(lang, code).value;
            } catch (__) {}
        }
        return (hljs as any).highlightAuto(code).value;
    }
} as any);

// GLOBAL message listener - must be set up at module level to catch messages
// that arrive before React's useEffect runs. This is critical for tool_result
// messages from Extension Host.
let globalWsClient: WebSocketClient | null = null;

window.addEventListener('message', (event) => {
    const message = event.data;
    if (!message || typeof message !== 'object') return;
    
    // Handle tool_result from Extension Host - forward to backend
    if (message.type === 'tool_result' && globalWsClient) {
        globalWsClient.send({ 
            type: 'tool_result', 
            call_id: message.call_id, 
            output: message.output 
        });
    }
});

// Improved Markdown to HTML converter using marked
const markdownToHtml = (text: string): string => {
    if (!text) return '';
    try {
        const rawHtml = marked.parse(text) as string;
        return DOMPurify.sanitize(rawHtml);
    } catch (e) {
        console.error('Markdown error:', e);
        return text;
    }
};

// Tool Mapping Helper
const mapToolToHuman = (name: string, args: any): string => {
    try {
        const a = typeof args === 'string' ? JSON.parse(args) : args;
        const argStr = (key: string) => {
            const val = a[key] || a['path'] || ''; // Fallback to 'path' if specific key undefined
            if (!val) return '';
            // Make paths clickable via message protocol
            // We return a specialized format that our ToolTraceItem can parse: [PATH](val)
            return ` <span class="clickable-path" data-path="${val}">${val}</span>`;
        };
        
        // Helper specifically for paths to ensure consistency
        const p = (key: string = 'path') => {
             const val = a[key] || (name.includes('file') ? a['path'] : '');
             return val ? ` ${val}` : '';
        }

        switch (name) {
            case 'read_file': return `Reading${p()}`;
            case 'write_file': return `Writing${p()}`;
            case 'create_file': return `Creating${p()}`;
            case 'edit_file': return `Editing${p()}`;
            case 'search_in_files': return `Searching "${a['pattern'] || ''}" in${p('path') || ' workspace'}`;
            case 'list_directory': return `Listing contents of${p()}`;
            case 'get_workspace_structure': return `Scanning directory structure${p('root')}`; // root or path?
            case 'get_file_outline': return `Analyzing structure of${p()}`;
            case 'find_references': return `Finding references for "${a['symbol']}"`;
            case 'get_workspace_diagnostics': return `Checking project diagnostics`;
            case 'run_terminal_command': 
                return `Exec: <span class="cmd-code">${a['command']}</span>`;
            case 'execute_vscode_command': return `VS Code: ${a['command']}`;
            default: return `${name} ${JSON.stringify(a).substring(0, 20)}`;
        }
    } catch {
        return name;
    }
};

interface ChatMessage {
    id?: string;
    role: 'user' | 'agent';
    text?: string;
    // Enhanced types for Process Timeline
    type?: 'text' | 'action_group' | 'step_start' | 'plan_created';
    row_type?: 'bubble' | 'step_container' | 'tool_trace' | 'plan_container';
    
    // Data for Plan
    plan_data?: {
        goal: string;
        steps: any[];
        isCollapsed?: boolean;
    };

    // Data for Step Container
    step_data?: {
        id: string;
        title: string;
        description: string;
        status: 'in_progress' | 'done' | 'failed';
        isCollapsed?: boolean;
    };
    
    // Data for Tool Trace
    tool_data?: {
        label: string;
        name?: string;
        args?: any;
        status: 'running' | 'success' | 'failure';
    };

    ttsStatus?: 'idle' | 'reading' | 'error';
    actions?: {
        type: 'thinking' | 'tool_start' | 'tool_end' | 'info';
        label: string;
        details?: string;
        status: 'running' | 'success' | 'failure';
        call_id?: string;
    }[];
}

const PlanContainerItem: React.FC<{ msg: ChatMessage, onToggle: () => void }> = ({ msg, onToggle }) => {
    const { plan_data } = msg;
    if (!plan_data) return null;

    const allDone = plan_data.steps && plan_data.steps.length > 0 && plan_data.steps.every((s: any) => s.status === 'done');
    const anyFailed = plan_data.steps && plan_data.steps.some((s: any) => s.status === 'failed');
    
    // Always show checkmark for the "Plan Created" step itself, unless failed.
    let icon = '✓';
    if (anyFailed) icon = '✗';

    // "Execution Plan" itself is an event that is done. Use .done class to dim it.
    // The visual checkmark indicates the plan is set.
    return (
        <div className={`timeline-plan ${plan_data.isCollapsed ? 'collapsed' : 'expanded'} done ${anyFailed ? 'failed' : ''}`}>
            <div className='timeline-plan-header' onClick={onToggle}>
                <div className='step-status-icon'>
                    {icon}
                </div>
                <div className='step-info'>
                    <span className='step-title'>Execution Plan</span>
                </div>
                <span className='step-toggle'>{plan_data.isCollapsed ? '▼' : '▲'}</span>
            </div>
            {!plan_data.isCollapsed && (
                <div className='timeline-plan-body'>
                    <div className='plan-goal'><strong>Goal:</strong> {plan_data.goal}</div>
                    <ul className='plan-steps'>
                        {plan_data.steps.map((s: any, i: number) => (
                            <li key={i}><strong>{i+1}. {s.title}</strong> - {s.description}</li>
                        ))}
                    </ul>
                </div>
            )}
            {/* Show just a checkmark or confirmation when collapsed? optional */}
        </div>
    );
};

const PlanStepItem: React.FC<{ msg: ChatMessage, onToggle: () => void }> = ({ msg, onToggle }) => {
    const { step_data } = msg;
    if (!step_data) return null;
    
    return (
        <div className={`timeline-step ${step_data.status} ${step_data.isCollapsed ? 'collapsed' : 'expanded'}`}>
            <div className='timeline-step-header' onClick={onToggle}>
                <div className='step-status-icon'>
                    {step_data.status === 'in_progress' && <span className='spinner-dots'></span>}
                    {step_data.status === 'done' && '✓'}
                    {step_data.status === 'failed' && '✗'}
                </div>
                <div className='step-info'>
                    <span className='step-title'>{step_data.title}</span>
                </div>
                 <span className='step-toggle'>{step_data.isCollapsed ? '▼' : '▲'}</span>
            </div>
            {!step_data.isCollapsed && (
                <div className='timeline-step-body'>
                    <div className='step-description-full'>{step_data.description}</div>
                </div>
            )}
        </div>
    );
};

const ToolTraceItem: React.FC<{ msg: ChatMessage }> = ({ msg }) => {
    const { tool_data } = msg;
    if (!tool_data) return null;
    
    const label = tool_data.name ? mapToolToHuman(tool_data.name, tool_data.args) : tool_data.label;

    return (
        <div className={`timeline-tool ${tool_data.status}`}>
            <span className='tool-status-icon'>
                {tool_data.status === 'running' && <span className='spinner-dots tiny'></span>}
                {tool_data.status === 'success' && '✓'}
                {tool_data.status === 'failure' && '✗'}
            </span>
            <span 
                className='tool-label' 
                dangerouslySetInnerHTML={{ __html: label }} 
                onClick={(e) => {
                    const target = e.target as HTMLElement;
                    if (target.classList.contains('clickable-path')) {
                        const path = target.getAttribute('data-path');
                        if (path) {
                            vscode.postMessage({ type: 'open_file', path });
                            e.stopPropagation();
                        }
                    }
                }}
            ></span>
        </div>
    );
};

const ActionStepItem: React.FC<{ action: NonNullable<ChatMessage['actions']>[0] }> = ({ action }) => {
    const [expanded, setExpanded] = React.useState(false);
    
    const getIcon = () => {
        if (action.status === 'running') return <span className='action-icon spinner'></span>;
        if (action.status === 'success') return <span className='action-icon success-icon'></span>;
        if (action.status === 'failure') return <span className='action-icon error-icon'></span>;
        return null;
    };

    return (
        <div className={'action-step ' + action.type + ' ' + action.status}>
            <div className='action-header' onClick={() => action.details && setExpanded(!expanded)}>
                {getIcon()}
                <span className='action-label'>{action.label}</span>
                {action.details && <span className='expand-icon'>{expanded ? '▼' : '▶'}</span>}
            </div>
            {expanded && action.details && (
                <div className='action-details'>
                    <pre>{action.details}</pre>
                </div>
            )}
        </div>
    );
};

const AgentFlow: React.FC<{ actions: ChatMessage['actions'] }> = ({ actions }) => {
    const [isExpanded, setIsExpanded] = useState(true);
    if (!actions || actions.length === 0) return null;

    return (
        <div className='agent-flow-container'>
            <div className='agent-flow-header' onClick={() => setIsExpanded(!isExpanded)}>
                <span className='flow-title'>Agent Workflow ({actions.length} steps)</span>
                <span className='expand-icon'>{isExpanded ? '▼' : '▶'}</span>
            </div>
            {isExpanded && (
                <div className='agent-flow-content'>
                    {actions.map((action, idx) => (
                        <ActionStepItem key={action.call_id || idx} action={action} />
                    ))}
                </div>
            )}
        </div>
    );
};

const BackendMenu: React.FC = () => {
    const [isOpen, setIsOpen] = useState(false);
    
    const toggleMenu = (e: React.MouseEvent) => {
        e.stopPropagation();
        setIsOpen(!isOpen);
    };
    
    const handleAction = (action: string) => {
        vscode.postMessage({ type: 'backend_action', action });
        setIsOpen(false);
    };

    useEffect(() => {
        const closeMenu = () => setIsOpen(false);
        if (isOpen) {
            window.addEventListener('click', closeMenu);
        }
        return () => window.removeEventListener('click', closeMenu);
    }, [isOpen]);

    return (
        <div className='backend-menu-container'>
            <button className='icon-btn' onClick={toggleMenu} title='Backend Settings'>
                ⚙️
            </button>
            {isOpen && (
                <div className='dropdown-menu' onClick={(e) => e.stopPropagation()}>
                    <div className='menu-item' onClick={() => handleAction('start')}>Start Backend</div>
                    <div className='menu-item' onClick={() => handleAction('stop')}>Stop Backend</div>
                    <div className='menu-item' onClick={() => handleAction('status')}>Status</div>
                    <div className='menu-item' onClick={() => handleAction('reconnect')}>Reconnect</div>
                </div>
            )}
        </div>
    );
};


// --- Timeline / Tree View Components ---

type LogData = {
    id: string;
    timestamp: string;
    type: string;
    category?: string;
    payload: any;
};

type StepNode = {
    id: string; // Step ID
    title: string;
    status: string;
    logs: LogData[];
};

type InteractionNode = {
    id: string; // Interaction UUID or 'SYSTEM'
    timestamp: string;
    title: string;
    steps: StepNode[];
    plan?: any; 
    logs: LogData[]; // Logs without step_id
};

const JsonViewer: React.FC<{ data: any, collapsed?: boolean }> = ({ data, collapsed = true }) => {
    const [isCollapsed, setIsCollapsed] = useState(collapsed);

    if (data === null) return <span className='json-null'>null</span>;
    if (data === undefined) return <span className='json-undefined'>undefined</span>;
    if (typeof data !== 'object') {
        if (typeof data === 'string' && data.includes('\n')) {
             return <div className='json-value string' style={{whiteSpace: 'pre-wrap', fontFamily: 'monospace', display: 'inline-block'}}>"{data}"</div>;
        }
        const typeClass = typeof data;
        return <span className={'json-value ' + typeClass}>{JSON.stringify(data)}</span>;
    }

    const isArray = Array.isArray(data);
    const keys = Object.keys(data);
    const isEmpty = keys.length === 0;

    if (isEmpty) return <span>{isArray ? '[]' : '{}'}</span>;

    return (
        <div className='json-viewer'>
            <div className='json-header' onClick={(e) => { e.stopPropagation(); setIsCollapsed(!isCollapsed); }}>
                <span className='expand-icon-small'>{isCollapsed ? '▶' : '▼'}</span>
                <span className='json-type'>{isArray ? 'Array(' + keys.length + ')' : 'Object'}</span>
            </div>
            {!isCollapsed && (
                <div className='json-body'>
                    {keys.map(key => (
                        <div key={key} className='json-entry'>
                            <span className='json-key'>{key}:</span>
                            <JsonViewer data={data[key]} collapsed={true} />
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

const LogTreeItem: React.FC<{ log: LogData }> = ({ log }) => {
    const [expanded, setExpanded] = useState(false);
    
    // Auto-expand errors
    useEffect(() => {
        if (log.type === 'ERROR') setExpanded(true);
    }, []);

    const isSimple = typeof log.payload !== 'object' || log.payload === null;

    return (
        <div className={'log-tree-item ' + (log.category ? 'log-' + log.category : '') + (log.type === 'ERROR' ? ' log-error' : '')}>
             <div className='log-header' onClick={() => !isSimple && setExpanded(!expanded)}>
                <span className='log-time'>{log.timestamp}</span>
                <span className={'log-type-tag ' + log.type}>{log.type}</span>
                {log.category && <span className='log-category-tag'>{log.category}</span>}
                <span className='log-preview'>
                    {isSimple ? String(log.payload) : (log.payload.component ? '[' + log.payload.component + '] ...' : '{...}')}
                </span>
             </div>
             {expanded && !isSimple && (
                 <div className='log-details-pane'>
                     <JsonViewer data={log.payload} collapsed={false} />
                 </div>
             )}
        </div>
    );
};

const StepTreeItem: React.FC<{ step: StepNode }> = ({ step }) => {
    const [expanded, setExpanded] = useState(step.status === 'in_progress');
    
    // Update expansion if status becomes in_progress
    useEffect(() => {
        if (step.status === 'in_progress') setExpanded(true);
    }, [step.status]);

    return (
        <div className={'step-tree-node ' + step.status}>
            <div className='step-header' onClick={() => setExpanded(!expanded)}>
                 <span className='expand-icon'>{expanded ? '▼' : '▶'}</span>
                 <span className='step-status-icon'>{step.status === 'done' ? '✅' : (step.status === 'in_progress' ? '⏳' : '⚪')}</span>
                 <span className='step-title'>Step {step.id}: {step.title}</span>
                 <span className='step-status-text'>({step.status})</span>
            </div>
            {expanded && (
                <div className='step-children'>
                    {step.logs.map(log => <LogTreeItem key={log.id} log={log} />)}
                </div>
            )}
        </div>
    );
};

const InteractionTreeItem: React.FC<{ node: InteractionNode, isLast: boolean }> = ({ node, isLast }) => {
    const [expanded, setExpanded] = useState(isLast); // Expand the latest one by default

    // If 'SYSTEM' and has recent logs, maybe expand? 
    // Stick to isLast for now.

    const isSystem = node.id === 'SYSTEM';

    return (
        <div className={'interaction-tree-node ' + (isSystem ? 'system-node' : '')}>
            <div className='interaction-header' onClick={() => setExpanded(!expanded)}>
                <span className='expand-icon-large'>{expanded ? '▼' : '▶'}</span>
                <span className='interaction-title'>{node.title}</span>
                <span className='interaction-time'>{node.timestamp}</span>
            </div>
            {expanded && (
                <div className='interaction-body'>
                    {node.plan && (
                         <div className='plan-summary'>
                             <strong>Goal:</strong> {node.plan.refined_goal}
                         </div>
                    )}
                    {/* Render Logs without Step ID */}
                    {node.logs.length > 0 && (
                        <div className='orphan-logs'>
                             {node.logs.map(log => <LogTreeItem key={log.id} log={log} />)}
                        </div>
                    )}
                    {/* Render Steps */}
                    {(node.steps || []).map(step => <StepTreeItem key={step.id} step={step} />)}
                </div>
            )}
        </div>
    );
};

const TimelineTree: React.FC<{ timeline: InteractionNode[], systemStatus: any }> = ({ timeline, systemStatus }) => {
    return (
        <div className='timeline-tree-container'>
             {systemStatus && (
                <div className='system-status-mini'>
                    <span className={'status-dot ' + (systemStatus.recorder?.error ? 'red' : 'green')}></span> Mic
                    <span className='sep'>|</span>
                    <span className={'status-dot ' + (systemStatus.llm ? 'green' : 'grey')}></span> LLM
                </div>
            )}
            {(!timeline || timeline.length === 0) ? <p className='no-data'>Waiting for events...</p> : (
                timeline.map((node, i) => node ? (
                    <InteractionTreeItem key={node.id} node={node} isLast={i === timeline.length - 1} />
                ) : null)
            )}
        </div>
    );
};


const App: React.FC = () => {
    const [activeTab, setActiveTab] = useState<'chat' | 'debug'>('chat');
    const [status, setStatus] = useState<string>('Ready');
    const [messages, setMessages] = useState<ChatMessage[]>([]);
    const [inputValue, setInputValue] = useState<string>('');
    const [isRecording, setIsRecording] = useState<boolean>(false);
    const [isSpeaking, setIsSpeaking] = useState<boolean>(false);
    const [ttsEnabled, setTtsEnabled] = useState<boolean>(() => {
        const saved = vscode.getState();
        return saved?.ttsEnabled !== undefined ? saved.ttsEnabled : true;
    });
    
    // Timeline State
    const [currentPlan, setCurrentPlan] = useState<any | null>(null);
    const [timeline, setTimeline] = useState<InteractionNode[]>([]);
    const [systemStatus, setSystemStatus] = useState<any | null>(null);

    const wsRef = useRef<WebSocketClient | null>(null);
    const connectionAttempted = useRef(false);
    const chatAreaRef = useRef<HTMLDivElement>(null);
    const shouldAutoScrollRef = useRef(true);
    const prevMessagesLengthRef = useRef(0);
    const prevLastMessageTextLengthRef = useRef(0);

    const handleScroll = () => {
        if (chatAreaRef.current) {
            const { scrollTop, scrollHeight, clientHeight } = chatAreaRef.current;
            const isAtBottom = Math.abs(scrollHeight - clientHeight - scrollTop) < 50;
            shouldAutoScrollRef.current = isAtBottom;
        }
    };

    // Timeline helpers refs
    const addToTimelineRef = useRef<(log: LogData, i_id?: string, s_id?: string) => void>(() => {});
    const updateTimelinePlanRef = useRef<(plan: any, i_id?: string) => void>(() => {});
    const updateStepStatusInTimelineRef = useRef<(s_id: string, s: string, i_id?: string) => void>(() => {});

    // Helper Implementations
    const addToTimeline = (log: LogData, interaction_id?: string, step_id?: string) => {
        setTimeline(prev => {
            if (!prev) return [];
            const newTimeline = [...prev];
            let targetId = interaction_id || 'SYSTEM';
            
            let nodeIndex = newTimeline.findIndex(n => n && n.id === targetId);
            if (nodeIndex === -1) {
                newTimeline.push({
                    id: targetId,
                    title: targetId === 'SYSTEM' ? 'System Events' : 'Active Task',
                    timestamp: log.timestamp,
                    steps: [],
                    logs: []
                });
                nodeIndex = newTimeline.length - 1;
            }

            const node = { ...newTimeline[nodeIndex] };
            if (!node) return newTimeline; // Should not happen

            if (step_id) {
                const currentSteps = node.steps || [];
                let stepIndex = currentSteps.findIndex(s => s.id === step_id);
                if (stepIndex === -1) {
                     node.steps = [...currentSteps, { id: step_id, title: 'Step ' + step_id, status: 'pending', logs: []}];
                     stepIndex = node.steps.length - 1;
                }
                const step = { ...node.steps[stepIndex] };
                step.logs = [...(step.logs || []), log];
                const newSteps = [...node.steps];
                newSteps[stepIndex] = step;
                node.steps = newSteps;
            } else {
                node.logs = [...(node.logs || []), log];
            }
            newTimeline[nodeIndex] = node;
            return newTimeline;
        });
    };

    const updateTimelinePlan = (plan: any, interaction_id?: string) => {
        setTimeline(prev => {
             if (!plan) return prev; // Guard against null plan
             if (!prev || prev.length === 0) return prev;
             const targetId = interaction_id || (prev.length > 0 ? prev[prev.length-1].id : 'new_task'); 
             let nodeIndex = prev.findIndex(n => n && n.id === targetId);
             if (nodeIndex === -1) return prev;
             
             const newTimeline = [...prev];
             const node = { ...newTimeline[nodeIndex] };
             
             // Sync steps
             const existingSteps = node.steps || [];
             const newSteps = (plan.steps || []).map((ps: any) => {
                 const existing = existingSteps.find((es: any) => es.id === ps.id);
                 if (existing) return { ...existing, title: ps.title, status: ps.status };
                 return { id: ps.id, title: ps.title, status: ps.status, logs: [] };
             });
             
             node.title = 'Task: ' + (plan.refined_goal || 'Unknown');
             node.plan = plan;
             node.steps = newSteps;
             newTimeline[nodeIndex] = node;
             return newTimeline;
        });
    };

    const updateStepStatusInTimeline = (step_id: string, status: string, interaction_id?: string) => {
         setTimeline(prev => {
             if (!prev) return [];
             return prev.map(node => {
                 if (!node) return node;
                 if (interaction_id && node.id !== interaction_id) return node;
                 if (!node.steps) return node;
                 
                 const stepIndex = node.steps.findIndex(s => s.id === step_id);
                 if (stepIndex !== -1) {
                     const newSteps = [...node.steps];
                     newSteps[stepIndex] = { ...newSteps[stepIndex], status: status as any };
                     return { ...node, steps: newSteps };
                 }
                 return node;
             });
         });
    };

    // Update refs on render
    useEffect(() => {
        addToTimelineRef.current = addToTimeline;
        updateTimelinePlanRef.current = updateTimelinePlan;
        updateStepStatusInTimelineRef.current = updateStepStatusInTimeline;
    }, [addToTimeline, updateTimelinePlan, updateStepStatusInTimeline]);

    useEffect(() => {
        if (chatAreaRef.current && activeTab === 'chat') {
            const currentLength = messages.length;
            const lastMsg = messages[messages.length - 1];
            const currentLastTextLength = lastMsg?.text?.length || 0;
            
            const isNewMessage = currentLength > prevMessagesLengthRef.current;
            // Only care about text length increase if it is the same last message being updated (streaming)
            // or a new message entirely.
            const isStreaming = currentLength === prevMessagesLengthRef.current && 
                                currentLastTextLength > prevLastMessageTextLengthRef.current;

            // Update refs for next time
            prevMessagesLengthRef.current = currentLength;
            prevLastMessageTextLengthRef.current = currentLastTextLength;

            if (shouldAutoScrollRef.current) {
                // Only scroll if something "added" to the view (new msg or more text)
                // This prevents scrolling when just toggling UI state like collapse/expand
                if (isNewMessage || isStreaming) {
                    chatAreaRef.current.scrollTop = chatAreaRef.current.scrollHeight;
                }
            }
        }
    }, [messages, activeTab]);

    const toggleRecording = async () => {
        if (!wsRef.current) return;
        if (!isRecording) {
            wsRef.current.send({ type: 'start_recording', payload: {} });
            setIsRecording(true);
            setStatus('Listening...');
        } else {
            wsRef.current.send({ type: 'stop_recording', payload: {} });
            setIsRecording(false);
            setStatus('Ready');
        }
    };
    const toggleRecordingRef = useRef(toggleRecording);
    useEffect(() => { toggleRecordingRef.current = toggleRecording; }, [toggleRecording]);

    useEffect(() => {
        vscode.setState({ ...vscode.getState(), ttsEnabled });
        if (wsRef.current) {
            wsRef.current.send({ type: 'toggle_tts', enabled: ttsEnabled } as any);
        }
    }, [ttsEnabled]);

    useEffect(() => {
        if (connectionAttempted.current) return;
        connectionAttempted.current = true;
        
        const client = new WebSocketClient();
        wsRef.current = client;
        globalWsClient = client; // Set global reference for message handler

        client.onStatus((s) => {
            if (s === 'connected') {
                setStatus('Ready');
                // Sync TTS state on connect
                client.send({ type: 'toggle_tts', enabled: ttsEnabled } as any);
            }
            else if (s === 'disconnected') setStatus('Offline');
            else if (s === 'connecting') setStatus('Connecting...');
            else setStatus(s);
        });

        client.connect();

        client.onMessage((msg: Message) => {
            const timestamp = new Date().toLocaleTimeString();

            if (msg.type === 'status') {
                setStatus(msg.status || 'Ready');
            } else if (msg.type === 'response') {
                if (msg.text) processAgentResponse(msg.text, msg.is_delta || false, msg.id);
            } else if (msg.type === 'tts_status') {
                setIsSpeaking(msg.status === 'started');
                setMessages(prev => prev.map(m => {
                    if (msg.message_id && m.id === msg.message_id) {
                        return { 
                            ...m, 
                            ttsStatus: msg.status === 'started' ? 'reading' : (msg.status === 'error' ? 'error' : 'idle') 
                        };
                    }
                    // If general stop, or start of another message, reset current message status
                    if (msg.status === 'stopped' || (msg.status === 'started' && m.ttsStatus === 'reading')) {
                        return { ...m, ttsStatus: 'idle' };
                    }
                    return m;
                }));
            } else if (msg.type === 'transcript') {
                if (msg.text) {
                    setMessages(prev => {
                         const lastMsg = prev[prev.length - 1];
                         if (lastMsg && lastMsg.role === 'user' && lastMsg.text === msg.text) return prev;
                         return [...prev, { role: 'user', text: msg.text || '', type: 'text' }];
                    });
                }
            } else if (msg.type === 'error') {
                setMessages(prev => [...prev, { role: 'agent', text: ' Error: ' + (msg.message || msg.error), type: 'text' }]);
                addToTimelineRef.current({ id: Date.now().toString(), timestamp, type: 'ERROR', payload: msg }, (msg as any).interaction_id);
                vscode.postMessage({ type: 'show_error', message: msg.message || msg.error });
            } else if (msg.type === 'plan_created') {
                const plan = (msg as any).payload || msg;
                setMessages(prev => [...prev, {
                    role: 'agent',
                    type: 'plan_created',
                    row_type: 'plan_container',
                    plan_data: {
                        goal: plan.refined_goal,
                        steps: plan.steps,
                        isCollapsed: true // Default to collapsed as requested
                    }
                }]);
            } else if (msg.type === 'step_start') {
                const step = (msg as any).payload || msg; // payload might be nested or direct
                setMessages(prev => {
                    // Auto-collapse all previous steps when a new one starts
                    const collapsedPrev = prev.map(m => 
                        m.row_type === 'step_container' && m.step_data
                            ? { ...m, step_data: { ...m.step_data, isCollapsed: true } }
                            : m
                    );
                    
                    return [...collapsedPrev, {
                        role: 'agent',
                        type: 'step_start', // Identifier for react key 
                        row_type: 'step_container',
                        step_data: {
                            id: step.id,
                            title: step.title,
                            description: step.description,
                            status: 'in_progress',
                            isCollapsed: false 
                        }
                    }];
                });
            } else if (msg.type === 'step_complete') {
                const { id, result } = (msg as any).payload || msg;
                setMessages(prev => prev.map(m => {
                    if (m.row_type === 'step_container' && m.step_data?.id === id) {
                        return {
                             ...m,
                             step_data: { ...m.step_data!, status: 'done', isCollapsed: true }
                        };
                    }
                    return m;
                }));
            } else if (msg.type === 'agent_action') {
                handleAgentAction(msg);
            } else if (msg.type === 'command') {
                if (msg.command === 'stop_recording') {
                    setIsRecording(false);
                    setStatus('Ready');
                } else if (msg.command === 'update_plan') {
                    setCurrentPlan(msg.payload);
                    addToTimelineRef.current({ id: Date.now().toString(), timestamp, type: 'PLAN_UPDATE', payload: msg.payload }, (msg as any).interaction_id);
                    updateTimelinePlanRef.current(msg.payload, (msg as any).interaction_id);
                } else if (msg.command === 'request_approval') {
                    // Show plan and wait for user approval
                    setCurrentPlan(msg.payload);
                    setStatus('waiting_approval');
                    addToTimelineRef.current({ id: Date.now().toString(), timestamp, type: 'PLAN_APPROVAL_NEEDED', payload: msg.payload }, (msg as any).interaction_id);
                    updateTimelinePlanRef.current(msg.payload, (msg as any).interaction_id);
                } else if (msg.command === 'update_step') {
                    if (msg.payload && msg.payload.id) {
                        setCurrentPlan((prev: any) => {
                            if (!prev) return prev;
                            const steps = prev.steps.map((s: any) => s.id === msg.payload.id ? { ...s, status: msg.payload.status } : s);
                            return { ...prev, steps };
                        });
                        updateStepStatusInTimelineRef.current(msg.payload.id, msg.payload.status, (msg as any).interaction_id);
                        addToTimelineRef.current({ id: Date.now().toString(), timestamp, type: 'STEP_UPDATE', payload: msg.payload }, (msg as any).interaction_id, msg.payload.id);
                    } else {
                        console.warn('update_step command missing payload.id:', msg);
                    }
                } else if (msg.command === 'system_status') {
                    setSystemStatus(msg.payload);
                    addToTimelineRef.current({ id: Date.now().toString(), timestamp, type: 'SYS_STATUS', payload: msg.payload }, 'SYSTEM');
                }
            } else if (msg.type === 'debug') {
                addToTimelineRef.current({ 
                    id: Date.now() + Math.random().toString(), 
                    timestamp, 
                    type: 'DEBUG', 
                    category: (msg as any).category, 
                    payload: (msg as any).data 
                }, (msg as any).interaction_id, (msg as any).step_id);

            } else if (msg.type === 'tool_usage') {
                console.log('VCCA Webview: Forwarding tool_usage to extension host:', msg.tool_name, msg.call_id);
                vscode.postMessage(msg);
            } else if (msg.type === 'tts_audio') {
                 setIsSpeaking(true);
                 setTimeout(() => setIsSpeaking(false), 3000);
            }
        });

        // Message listener for toggle_voice and reconnect commands
        // NOTE: tool_result is handled by the GLOBAL listener at module level
        // because useEffect runs after render and may miss early messages
        const messageListener = (event: MessageEvent) => {
            const message = event.data;
            if (!message || typeof message !== 'object') return;
            
            if (message.type === 'toggle_voice') {
                toggleRecordingRef.current?.();
            } else if (message.type === 'reconnect') {
                wsRef.current?.connect();
            }
        };

        window.addEventListener('message', messageListener);
        return () => window.removeEventListener('message', messageListener);
    }, []);

    const handleAgentAction = (msg: Message) => {
        console.log('VCCA handleAgentAction:', msg.action_type, msg.tool_name, msg.call_id);
        if (msg.action_type === 'tool_start') {
             // Generate human-readable label using tool name and args
             const humanLabel = msg.tool_name 
                 ? mapToolToHuman(msg.tool_name, msg.input_data || {})
                 : (msg.action_label || 'Tool Execution');
             
             setMessages(prev => [...prev, {
                 role: 'agent',
                 row_type: 'tool_trace',
                 tool_data: {
                     label: humanLabel,
                     name: msg.tool_name,
                     args: msg.input_data,
                     status: 'running'
                 },
                 // Use actions array to store call_id for lookup
                 actions: [{ call_id: msg.call_id, type: 'tool_start', label: humanLabel, status: 'running' }]
             }]);
        } else if (msg.action_type === 'tool_end') {
             setMessages(prev => prev.map(m => {
                 // Find the row that matches this call_id
                 if (m.row_type === 'tool_trace' && m.actions?.[0]?.call_id === msg.call_id) {
                     return {
                         ...m,
                         tool_data: {
                             ...m.tool_data!,
                             status: (msg.action_status as any) || 'success'
                         }
                     };
                 }
                 return m;
             }));
        } 
    };

    const processAgentResponse = (text: string, isDelta: boolean, id?: string) => {
        setMessages(prev => {
            const lastMsg = prev[prev.length - 1];
            if (isDelta && lastMsg && lastMsg.role === 'agent' && lastMsg.type === 'text') {
                return [...prev.slice(0, -1), { ...lastMsg, text: lastMsg.text + text, id: id || lastMsg.id }];
            } else {
                return [...prev, { role: 'agent', text, type: 'text', id }];
            }
        });
    };

    const handleSend = () => {
        if (!inputValue.trim() || !wsRef.current) return;
        shouldAutoScrollRef.current = true;
        setMessages(prev => [...prev, { role: 'user', text: inputValue, type: 'text' }]);
        wsRef.current.send({
            type: 'text_input',
            text: inputValue,
            id: Date.now().toString()
        });
        setInputValue('');
    };

    const handleResume = () => {
        if (!wsRef.current) return;
        wsRef.current.send({
            type: 'text_input',
            text: 'resume',
            id: Date.now().toString()
        });
    };

    const handleStopSpeaking = () => {
        if (!wsRef.current) return;
        wsRef.current.send({
            type: 'stop_generation',
            payload: {}
        });
        setIsSpeaking(false);
    };

    useEffect(() => {
        vscode.postMessage({ type: 'update_status', status });
    }, [status]);

    return (
        <div className='container' onClick={() => status === 'Sound Blocked - Click anywhere' && setStatus('ready')}>
            <header>
                <div className='tab-bar'>
                    <button 
                        className={'tab-btn ' + (activeTab === 'chat' ? 'active' : '')}
                        onClick={() => setActiveTab('chat')}
                    >
                        Chat
                    </button>
                    <button 
                        className={'tab-btn ' + (activeTab === 'debug' ? 'active' : '')}
                        onClick={() => setActiveTab('debug')}
                    >
                        Debug {currentPlan ? '(Active)' : ''}
                    </button>
                </div>

                <div className='header-right'>
                    <div className='status-container'>
                        <span className={'status-indicator ' + status.toLowerCase().replace(/ /g, '-').split('(')[0]}></span>
                        <span className='status-text'>{status}</span>
                    </div>
                    <label className='tts-toggle' title='Toggle Auto-TTS'>
                        <input 
                            type='checkbox' 
                            checked={ttsEnabled} 
                            onChange={(e) => setTtsEnabled(e.target.checked)} 
                        />
                        <span className='tts-label'>{ttsEnabled ? '🔊' : '🔇'}</span>
                    </label>

                    {isSpeaking && (
                         <button className='stop-speaking-btn' onClick={handleStopSpeaking} title='Stop TTS'>
                              Stop
                         </button>
                    )}

                    {isRecording && (
                        <div className='mic-active-badge'>
                            <span className='mic-icon-small'></span>
                            <span className='listening-pulse'>Listening...</span>
                        </div>
                    )}
                    
                    {currentPlan && (
                        <button className='resume-btn-header' onClick={handleResume} title='Resume pending plan'>
                             Resume
                        </button>
                    )}
                    <BackendMenu />
                </div>
            </header>
            
            {activeTab === 'chat' ? (
                <div className='chat-area' ref={chatAreaRef} onScroll={handleScroll}>
                    {messages.length === 0 && <p className='welcome'>Speak or type a command to start coding.</p>}
                    
                    {messages.map((m, i) => {
                        if (m.row_type === 'plan_container') {
                            return <PlanContainerItem key={i} msg={m} onToggle={() => {
                                setMessages(prev => prev.map((msg, idx) => idx === i ? 
                                    { ...msg, plan_data: { ...msg.plan_data!, isCollapsed: !msg.plan_data!.isCollapsed } } : msg
                                ));
                            }} />;
                        }
                        if (m.row_type === 'step_container') {
                            return <PlanStepItem key={i} msg={m} onToggle={() => {
                                setMessages(prev => prev.map((msg, idx) => idx === i ? 
                                    { ...msg, step_data: { ...msg.step_data!, isCollapsed: !msg.step_data!.isCollapsed } } : msg
                                ));
                            }} />;
                        }
                        if (m.row_type === 'tool_trace') {
                            return <ToolTraceItem key={i} msg={m} />;
                        }
                        
                        // Determine style: User gets bubbles, Agent gets plain text
                        const isAgentText = m.role === 'agent' && m.type !== 'action_group';
                        const containerClass = isAgentText 
                            ? 'agent-message-plain' 
                            : 'message ' + m.role + ' ' + (m.type || 'text');

                        return (
                        <div key={i} className={containerClass}>
                            {m.type === 'action_group' ? (
                                <AgentFlow actions={m.actions} />
                            ) : (
                                <>
                                    <div dangerouslySetInnerHTML={{ __html: markdownToHtml(m.text || '') }} />
                                    {m.role === 'agent' && (
                                        <div className='message-tts-controls'>
                                            {m.ttsStatus === 'reading' && (
                                                <div className='tts-active-indicators'>
                                                    <span className='speaker-icon active' title='Reading...'>🔊</span>
                                                    <button className='tts-stop-btn' onClick={handleStopSpeaking} title='Stop reading'>⏹️</button>
                                                </div>
                                            )}
                                            {m.ttsStatus === 'error' && (
                                                <span className='speaker-icon error' title='TTS Error'>🔊</span>
                                            )}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    );
                    })}
                </div>
            ) : (
                <div className='chat-area debug-container'>
                    <TimelineTree timeline={timeline} systemStatus={systemStatus} />
                </div>
            )}

            {status === 'waiting_approval' && currentPlan && (
                <div className='approval-panel'>
                    <div className='approval-header'>
                        <span>⏸️ Plan Awaiting Approval</span>
                    </div>
                    <div className='approval-actions'>
                        <button 
                            className='approve-btn' 
                            onClick={() => {
                                wsRef.current?.send({ type: 'approve_plan' });
                                setStatus('processing');
                            }}
                        >
                            ✓ Approve & Execute
                        </button>
                        <button 
                            className='reject-btn' 
                            onClick={() => {
                                wsRef.current?.send({ type: 'reject_plan' });
                                setCurrentPlan(null);
                                setStatus('Ready');
                            }}
                        >
                            ✗ Reject
                        </button>
                    </div>
                </div>
            )}

            <div className='input-area'>
                <textarea 
                    value={inputValue} 
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setInputValue(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            handleSend();
                        }
                    }}
                    placeholder='Ask me something...'
                    rows={3}
                />
                <div className='input-actions'>
                    <button 
                        className={'mic-btn-small ' + (isRecording ? 'recording' : '')} 
                        onClick={toggleRecording}
                        title={isRecording ? 'Stop Recording' : 'Start Voice Control'}
                    >
                        {isRecording ? '⏹' : '🎤'}
                    </button>
                    {(status === 'thinking' || status === 'processing') ? (
                        <button 
                            className='stop-btn-small' 
                            onClick={() => wsRef.current?.send({ type: 'stop_generation' })}
                            title='Stop Generation'
                        >
                            ⬜
                        </button>
                    ) : (
                        <button onClick={handleSend} className='send-btn-small' title='Send Message'>
                            ➤
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

export default App;



