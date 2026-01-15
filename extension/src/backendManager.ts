import * as vscode from 'vscode';
import * as path from 'path';
import * as cp from 'child_process';
import * as fs from 'fs';

export class BackendManager {
    private static instance: BackendManager;
    private process: cp.ChildProcess | undefined;
    private outputChannel: vscode.OutputChannel;

    private constructor() {
        this.outputChannel = vscode.window.createOutputChannel('VCCA Backend');
    }

    public static getInstance(): BackendManager {
        if (!BackendManager.instance) {
            BackendManager.instance = new BackendManager();
        }
        return BackendManager.instance;
    }

    public async start(preferredPythonPath?: string, apiKey?: string): Promise<void> {
        if (this.process) {
            return;
        }

        const config = vscode.workspace.getConfiguration('vcca');
        let pythonPath = preferredPythonPath || config.get<string>('pythonPath') || 'python';
        const port = config.get<number>('port') || 8775;

        // Ensure port is free on Windows before starting
        if (process.platform === 'win32') {
            try {
                // Check if port is in use
                const checkPort = cp.execSync(`netstat -aon | findstr :${port} | findstr LISTENING`, { encoding: 'utf8' }).trim();
                if (checkPort) {
                    this.outputChannel.appendLine(`Port ${port} is occupied. Cleaning up...`);
                    cp.execSync(`powershell -Command "Get-NetTCPConnection -LocalPort ${port} -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"`);
                    // Wait for the socket to be released by the OS
                    await new Promise(resolve => setTimeout(resolve, 1500));
                    this.outputChannel.appendLine(`Cleanup finished.`);
                }
            } catch (e) {
                // No process found or error, continue
            }
        }

        const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        
        // Auto-detect venv if pythonPath is default and no preferred path given
        if (pythonPath === 'python' && workspaceRoot) {
            const venvPath = process.platform === 'win32' 
                ? path.join(workspaceRoot, '.venv', 'Scripts', 'python.exe')
                : path.join(workspaceRoot, '.venv', 'bin', 'python');
            
            if (fs.existsSync(venvPath)) {
                pythonPath = venvPath;
            }
        }

        // We assume backend is in [extensionPath]/backend for bundled version
        // or a sibling for dev version
        const extensionPath = vscode.extensions.getExtension('undefined_publisher.vcca')?.extensionPath 
            || path.join(__dirname, '..');

        let backendRoot = extensionPath;
        let scriptPath = path.join(extensionPath, 'backend', 'src', 'main.py');

        if (!fs.existsSync(scriptPath)) {
            // Development fallback: check sibling folder
            const devBackendPath = path.join(extensionPath, '..', 'backend', 'src', 'main.py');
            if (fs.existsSync(devBackendPath)) {
                backendRoot = path.join(extensionPath, '..');
                scriptPath = devBackendPath;
            }
        }

        this.outputChannel.appendLine(`Starting backend from: ${scriptPath}`);
        this.outputChannel.appendLine(`CWD: ${workspaceRoot || 'None (No workspace open)'}`);
        this.outputChannel.appendLine(`Python Path: ${pythonPath}`);

        // Environment variables - PYTHONPATH must point to the folder CONTAINING 'backend' package
        const env: { [key: string]: string | undefined } = { ...process.env };
        
        if (apiKey) {
            env['GEMINI_API_KEY'] = apiKey;
        }
        
        env['BACKEND_PORT'] = port.toString();
        env['BACKEND_HOST'] = '127.0.0.1';
        
        const pyPathKey = Object.keys(env).find(k => k.toUpperCase() === 'PYTHONPATH') || 'PYTHONPATH';
        const existingPyPath = env[pyPathKey];
        // Must include extension root to find 'backend' package
        env[pyPathKey] = existingPyPath ? `${backendRoot}${path.delimiter}${existingPyPath}` : backendRoot;
        
        this.outputChannel.appendLine(`PYTHONPATH: ${env[pyPathKey]}`);
        this.outputChannel.show();

        this.process = cp.spawn(pythonPath, ['-m', 'backend.src.main'], {
            cwd: workspaceRoot || extensionPath,
            env: env
        });

        this.process.stdout?.on('data', (data) => {
            this.outputChannel.append(`[STDOUT]: ${data}`);
        });

        this.process.stderr?.on('data', (data) => {
            this.outputChannel.append(`[STDERR]: ${data}`);
        });

        this.process.on('close', (code) => {
            this.outputChannel.appendLine(`Backend process exited with code ${code}`);
            this.process = undefined;
        });

        vscode.window.showInformationMessage(`VCCA Backend started on port ${port}`);
    }

    public isRunning(): boolean {
        return !!this.process && !this.process.killed;
    }

    public stop(): void {
        if (this.process) {
            if (process.platform === 'win32') {
                // On Windows, kill the process tree to ensure all sub-processes (like Python) are gone
                try {
                    cp.execSync(`taskkill /F /T /PID ${this.process.pid}`);
                } catch (e) {
                    this.outputChannel.appendLine(`Error using taskkill: ${e}`);
                    this.process.kill();
                }
            } else {
                this.process.kill();
            }
            this.process = undefined;
            this.outputChannel.appendLine('Backend process killed.');
        } else if (process.platform === 'win32') {
            // Fallback: kill anything on the configured port if we lost track of the process
            const config = vscode.workspace.getConfiguration('vcca');
            const port = config.get<number>('port') || 8775;
            try {
                cp.execSync(`powershell -Command "Get-NetTCPConnection -LocalPort ${port} -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"`);
                this.outputChannel.appendLine(`Cleaned up orphaned processes on port ${port}.`);
            } catch (e) {
                // No process found
            }
        }
    }
}
