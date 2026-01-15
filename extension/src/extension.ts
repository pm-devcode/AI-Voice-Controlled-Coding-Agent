import * as vscode from 'vscode';
import * as cp from 'child_process';
import { BackendManager } from './backendManager';
import { ChatViewProvider } from './chatViewProvider';
import { VenvManager } from './venvManager';

export async function activate(context: vscode.ExtensionContext) {
    console.log('VCCA Extension is now active');

    const venvManager = new VenvManager(context);
    await venvManager.ensureVenv();

    const backendManager = BackendManager.getInstance();

    // Command to set API Key
    context.subscriptions.push(
        vscode.commands.registerCommand('vcca.setApiKey', async () => {
            const currentKey = await context.secrets.get('gemini_api_key');
            const key = await vscode.window.showInputBox({
                prompt: "Enter your Gemini API Key",
                placeHolder: currentKey ? "••••••••" : "Paste your key here",
                password: true
            });

            if (key !== undefined) {
                await context.secrets.store('gemini_api_key', key);
                vscode.window.showInformationMessage('VCCA: API Key saved successfully.');
                
                // If backend is running, offer to restart
                const restart = 'Restart Backend';
                vscode.window.showInformationMessage('VCCA: Restart the backend to apply the new API Key?', restart)
                    .then(selection => {
                        if (selection === restart) {
                            backendManager.stop();
                            backendManager.start(venvManager.pythonPath, key);
                        }
                    });
            }
        })
    );

    // Initial check for API Key
    const initialApiKey = await context.secrets.get('gemini_api_key');
    if (!initialApiKey) {
        vscode.window.showWarningMessage('VCCA: Gemini API Key is missing.', 'Set API Key').then(selection => {
            if (selection === 'Set API Key') {
                vscode.commands.executeCommand('vcca.setApiKey');
            }
        });
    }

    const chatProvider = new ChatViewProvider(context.extensionUri);

    // Register Sidebar View
    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider(ChatViewProvider.viewType, chatProvider)
    );

    // Register Commands
    context.subscriptions.push(
        vscode.commands.registerCommand('vcca.start', async () => {
            const key = await context.secrets.get('gemini_api_key');
            backendManager.start(venvManager.pythonPath, key);
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('vcca.stop', () => {
            backendManager.stop();
            vscode.window.showInformationMessage('VCCA Backend stopped.');
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('vcca.status', async () => {
            const running = backendManager.isRunning();
            let portInfo = 'Unknown';
            
            if (process.platform === 'win32') {
                try {
                    const config = vscode.workspace.getConfiguration('vcca');
                    const port = config.get<number>('port') || 8775;
                    const output = cp.execSync(`netstat -aon | findstr :${port} | findstr LISTENING`).toString();
                    if (output.includes('LISTENING')) {
                        portInfo = `Listening on port ${port}`;
                    }
                } catch {
                    portInfo = 'Port not in use';
                }
            }

            vscode.window.showInformationMessage(`VCCA Backend status: ${running ? 'Running' : 'Stopped'} (${portInfo})`);
            return running;
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('vcca.reconnect', async () => {
            backendManager.stop();
            const key = await context.secrets.get('gemini_api_key');
            await backendManager.start(venvManager.pythonPath, key);
            // Tell webview to reconnect
            chatProvider.reconnect();
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('vcca.toggleVoice', () => {
            chatProvider.toggleVoice();
        })
    );

    // Initial start with private venv
    backendManager.start(venvManager.pythonPath, initialApiKey);

    // Cleanup
    context.subscriptions.push({
        dispose: () => backendManager.stop()
    });
}

export function deactivate() {
    BackendManager.getInstance().stop();
}
