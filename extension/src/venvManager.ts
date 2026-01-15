import * as vscode from 'vscode';
import * as path from 'path';
import * as cp from 'child_process';
import * as fs from 'fs';
import { promisify } from 'util';

const exec = promisify(cp.exec);

export class VenvManager {
    constructor(private context: vscode.ExtensionContext) {}

    public get pythonPath(): string {
        const venvDir = this.getVenvDir();
        const pythonInVenv = process.platform === 'win32'
            ? path.join(venvDir, 'Scripts', 'python.exe')
            : path.join(venvDir, 'bin', 'python');
        
        return fs.existsSync(pythonInVenv) ? pythonInVenv : 'python';
    }

    private getVenvDir(): string {
        return path.join(this.context.globalStorageUri.fsPath, 'venv');
    }

    private getSentinelPath(): string {
        return path.join(this.getVenvDir(), 'vcca_setup_done.txt');
    }

    public async ensureVenv(): Promise<void> {
        const venvDir = this.getVenvDir();
        const sentinelPath = this.getSentinelPath();
        
        if (fs.existsSync(sentinelPath) && fs.existsSync(this.pythonPath)) {
            console.log('VCCA: Private venv already exists and is fully set up.');
            return;
        }

        await vscode.window.withProgress({
            location: vscode.ProgressLocation.Notification,
            title: "VCCA: Setting up AI Backend (this may take a few minutes)...",
            cancellable: false
        }, async (progress) => {
            try {
                // Ensure storage dir exists
                if (!fs.existsSync(this.context.globalStorageUri.fsPath)) {
                    fs.mkdirSync(this.context.globalStorageUri.fsPath, { recursive: true });
                }

                if (!fs.existsSync(this.pythonPath)) {
                    progress.report({ message: "Creating virtual environment..." });
                    await exec(`python -m venv "${venvDir}"`);
                }

                progress.report({ message: "Installing dependencies (Whisper, Gemini, etc)..." });
                
                // Try to find requirements.txt (dev vs bundled path)
                let requirementsPath = path.join(this.context.extensionPath, 'backend', 'requirements.txt');
                if (!fs.existsSync(requirementsPath)) {
                    // In progress development, backend is likely a sibling of extension
                    requirementsPath = path.join(this.context.extensionPath, '..', 'backend', 'requirements.txt');
                }

                if (!fs.existsSync(requirementsPath)) {
                    throw new Error(`Could not find requirements.txt at ${requirementsPath}`);
                }
                
                // Use the newly created python to install
                const pipCmd = process.platform === 'win32'
                    ? `"${path.join(venvDir, 'Scripts', 'pip.exe')}"`
                    : `"${path.join(venvDir, 'bin', 'pip')}"`;
                
                await exec(`${pipCmd} install -r "${requirementsPath}"`);
                
                // Create sentinel file on success
                fs.writeFileSync(sentinelPath, `Setup completed on ${new Date().toISOString()}`);

                vscode.window.showInformationMessage('VCCA: AI Backend setup completed successfully.');
            } catch (err: any) {
                console.error('Venv setup failed:', err);
                vscode.window.showErrorMessage(`VCCA: Setup failed: ${err.message}`);
                throw err;
            }
        });
    }
}
