export interface Message {
    type: 'config' | 'audio_chunk' | 'text_input' | 'status' | 'transcript' | 'response' | 'error' | 'ping' | 'tool_usage' | 'tool_result' | 'tts_audio' | 'agent_action' | 'stop_generation' | 'command' | 'clear_context' | 'start_recording' | 'stop_recording' | 'debug' | 'backend_action' | 'approve_plan' | 'reject_plan' | 'toggle_tts' | 'tts_status' | 'step_start' | 'step_complete' | 'plan_created';
    text?: string;
    // data?: string; // Removed duplicate
    status?: 'connecting' | 'connected' | 'disconnected' | 'started' | 'stopped' | 'error' | string;
    message?: string;
    message_id?: string;
    is_delta?: boolean;
    is_final?: boolean;
    id?: string;
    enabled?: boolean;
    // For command messages
    command?: string;
    args?: any;
    payload?: any;
    // For debug logs
    category?: string; // "llm", "tool", "system"
    data?: any;       // The raw debug data (Unified)
    interaction_id?: string;
    step_id?: string;
    // New fields for agent actions/thoughts
    action_type?: 'thinking' | 'tool_start' | 'tool_end' | 'info';
    action_label?: string;
    action_details?: string;
    action_status?: 'running' | 'success' | 'failure';
    tool_name?: string;
    input_data?: any;
    call_id?: string;
    output?: any;
    // backend action
    action?: string;
    // Error
    error?: string;
}

export class WebSocketClient {
    private ws: WebSocket | null = null;
    private url: string;
    private onMessageCallbacks: ((msg: Message) => void)[] = [];
    private onStatusCallbacks: ((status: 'connecting' | 'connected' | 'disconnected') => void)[] = [];
    private reconnectAttempts = 0;
    private maxReconnectDelay = 10000;

    constructor(port?: number) {
        // Use port from config or default to 8775
        const actualPort = port || (window as any).VCCA_CONFIG?.port || 8775;
        // Use 127.0.0.1 instead of localhost to avoid IPv6 issues on Windows
        this.url = `ws://127.0.0.1:${actualPort}/ws`;
    }

    public connect() {
        console.log(`Connecting to ${this.url}...`);
        this.notifyStatus('connecting');
        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
            console.log('WS Connected');
            this.reconnectAttempts = 0;
            this.notifyStatus('connected');
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data) as Message;
                this.onMessageCallbacks.forEach(cb => cb(data));
            } catch (e) {
                console.error('Error parsing WS message', e);
            }
        };

        this.ws.onclose = (event) => {
            this.notifyStatus('disconnected');
            console.log(`WS Closed: code=${event.code}, reason=${event.reason}, wasClean=${event.wasClean}`);
            if (event.wasClean) {
                console.log('WS Closed cleanly');
            } else {
                console.log('WS Connection lost - attempting reconnect');
                const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), this.maxReconnectDelay);
                console.log(`Reconnecting in ${delay}ms...`);
                setTimeout(() => {
                    this.reconnectAttempts++;
                    this.connect();
                }, delay);
            }
        };

        this.ws.onerror = (error) => {
            console.error('WS Error:', error);
            // On some VS Code versions, error doesn't contain much info, 
            // but we can at least log that it happened.
            this.notifyStatus('disconnected');
        };
    }

    private notifyStatus(status: 'connecting' | 'connected' | 'disconnected') {
        this.onStatusCallbacks.forEach(cb => cb(status));
    }

    public onStatus(callback: (status: 'connecting' | 'connected' | 'disconnected') => void) {
        this.onStatusCallbacks.push(callback);
    }

    public send(msg: Message) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(msg));
        }
    }

    public onMessage(callback: (msg: Message) => void) {
        this.onMessageCallbacks.push(callback);
    }
}
