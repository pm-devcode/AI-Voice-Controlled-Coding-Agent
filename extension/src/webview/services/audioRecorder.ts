export class AudioRecorder {
    private audioContext: AudioContext | null = null;
    private processor: ScriptProcessorNode | null = null;
    private input: MediaStreamAudioSourceNode | null = null;
    private stream: MediaStream | null = null;
    private onDataCallback: (base64Data: string) => void;

    constructor(onData: (base64Data: string) => void) {
        this.onDataCallback = onData;
    }

    public async start(): Promise<void> {
        try {
            // Check for API support
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                // Should not happen in modern VS Code unless restricted by policy
                throw new Error("Audio API not supported in this environment");
            }

            this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            
            // Re-create AudioContext if closed
            const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
            this.audioContext = new AudioContextClass({
                sampleRate: 16000, 
            });

            this.input = this.audioContext.createMediaStreamSource(this.stream);
            
            // Note: ScriptProcessor is deprecated but easiest for raw PCM access in VS Code Webview 
            // without complex AudioWorklet setup for MVP.
            this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);

            this.input.connect(this.processor);
            this.processor.connect(this.audioContext.destination);

            this.processor.onaudioprocess = (e) => {
                const inputData = e.inputBuffer.getChannelData(0);
                const pcmData = this.floatTo16BitPCM(inputData);
                const base64 = this.base64ArrayBuffer(pcmData);
                this.onDataCallback(base64);
            };

            console.log('Recording started');
        } catch (err) {
            console.error('Failed to start recording:', err);
            throw err;
        }
    }

    public stop(): void {
        if (this.processor) {
            this.processor.disconnect();
            this.processor.onaudioprocess = null;
            this.processor = null;
        }
        if (this.input) {
            this.input.disconnect();
            this.input = null;
        }
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }
        console.log('Recording stopped');
    }

    private floatTo16BitPCM(input: Float32Array): ArrayBuffer {
        const buffer = new ArrayBuffer(input.length * 2);
        const view = new DataView(buffer);
        let offset = 0;
        for (let i = 0; i < input.length; i++, offset += 2) {
            const s = Math.max(-1, Math.min(1, input[i]));
            view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
        }
        return buffer;
    }

    private base64ArrayBuffer(arrayBuffer: ArrayBuffer): string {
        let binary = '';
        const bytes = new Uint8Array(arrayBuffer);
        const len = bytes.byteLength;
        for (let i = 0; i < len; i++) {
            binary += String.fromCharCode(bytes[i]);
        }
        return window.btoa(binary);
    }
}
