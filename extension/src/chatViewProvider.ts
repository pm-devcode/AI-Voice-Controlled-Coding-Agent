import * as vscode from 'vscode';
import * as cp from 'child_process';

export class ChatViewProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'vcca.chatView';
    private _view?: vscode.WebviewView;

    constructor(private readonly _extensionUri: vscode.Uri) {}

    public toggleVoice() {
        if (this._view) {
            this._view.show?.(true); // Ensure view is visible
            this._view.webview.postMessage({ type: 'toggle_voice' });
        }
    }

    public reconnect() {
        if (this._view) {
            this._view.webview.postMessage({ type: 'reconnect' });
        }
    }

    public resolveWebviewView(
        webviewView: vscode.WebviewView,
        _context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken,
    ) {
        this._view = webviewView;

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [this._extensionUri]
        };

        webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);

        webviewView.webview.onDidReceiveMessage(async data => {
            switch (data.type) {
                case 'tool_usage': {
                    console.log(`VCCA: Processing tool_usage for ${data.tool_name}, call_id=${data.call_id}`);
                    try {
                        const result = await this._handleToolUsage(data);
                        console.log(`VCCA: Tool ${data.tool_name} completed, result length=${typeof result === 'string' ? result.length : JSON.stringify(result).length}`);
                        
                        // Check if webview is still available
                        if (!this._view || !this._view.webview) {
                            console.error('VCCA: Webview is no longer available!');
                            return;
                        }
                        
                        const posted = await this._view.webview.postMessage({
                            type: 'tool_result',
                            call_id: data.call_id,
                            output: result
                        });
                        console.log(`VCCA: postMessage returned: ${posted} for call_id=${data.call_id}`);
                    } catch (err: any) {
                        console.error(`VCCA: Tool ${data.tool_name} failed:`, err);
                        if (this._view?.webview) {
                            await this._view.webview.postMessage({
                                type: 'tool_result',
                                call_id: data.call_id,
                                output: `Error: ${err.message}`
                            });
                        }
                    }
                    break;
                }
                case 'webview_log': {
                    // Forward logs from webview to extension host console
                    console.log(`VCCA Webview Log: ${data.message}`, data.data || '');
                    break;
                }
                case 'backend_action':
                    switch (data.action) {
                        case 'start':
                            vscode.commands.executeCommand('vcca.start');
                            break;
                        case 'stop':
                            vscode.commands.executeCommand('vcca.stop');
                            break;
                        case 'reconnect':
                            vscode.commands.executeCommand('vcca.reconnect');
                            break;
                        case 'status':
                            vscode.commands.executeCommand('vcca.status');
                            break;
                    }
                    break;
                case 'show_error':
                    vscode.window.showErrorMessage(`VCCA Error: ${data.message}`);
                    break;
                case 'update_status':
                    if (this._view) {
                        this._view.description = data.status;
                    }
                    break;
            }
        });
    }

    private async _handleToolUsage(data: any): Promise<any> {
        const { tool_name, input_data } = data;
        const workspaceFolders = vscode.workspace.workspaceFolders;
        const workspaceRoot = workspaceFolders ? workspaceFolders[0].uri : undefined;

        console.log(`VCCA Tool Call: ${tool_name}`, input_data);

        if (!workspaceRoot) {
            console.error("VCCA: No workspace folder open.");
            return "No workspace folder open";
        }

        try {
            switch (tool_name) {
                case 'read_file': {
                    const path = input_data.path || '';
                    const fileUri = path.startsWith('/') || path.includes(':') 
                        ? vscode.Uri.file(path) 
                        : vscode.Uri.joinPath(workspaceRoot, path);
                    const content = await vscode.workspace.fs.readFile(fileUri);
                    return new TextDecoder().decode(content);
                }
                case 'write_file': {
                    const path = input_data.path || '';
                    const fileUri = path.startsWith('/') || path.includes(':') 
                        ? vscode.Uri.file(path) 
                        : vscode.Uri.joinPath(workspaceRoot, path);
                    const encoder = new TextEncoder();
                    await vscode.workspace.fs.writeFile(fileUri, encoder.encode(input_data.content));
                    return "success";
                }
                case 'list_dir': {
                    const path = input_data.path || '.';
                    const dirUri = path.startsWith('/') || path.includes(':') 
                        ? vscode.Uri.file(path) 
                        : vscode.Uri.joinPath(workspaceRoot, path);
                    const entries = await vscode.workspace.fs.readDirectory(dirUri);
                    return entries.map(([name, _type]) => name);
                }
                case 'get_active_file_context': {
                    const editor = vscode.window.activeTextEditor;
                    if (!editor) return "No active editor";
                    
                    const doc = editor.document;
                    const selection = editor.selection;
                    const text = doc.getText(selection) || doc.getText(); // Selection or whole file
                    
                    return {
                        path: vscode.workspace.asRelativePath(doc.uri),
                        language: doc.languageId,
                        content: text,
                        selection: {
                            start: selection.start.line,
                            end: selection.end.line
                        }
                    };
                }
                case 'get_workspace_diagnostics': {
                    const diagnostics = vscode.languages.getDiagnostics();
                    return diagnostics.map(([uri, diagList]) => ({
                        file: vscode.workspace.asRelativePath(uri),
                        errors: diagList.map(d => ({
                            message: d.message,
                            severity: vscode.DiagnosticSeverity[d.severity],
                            line: d.range.start.line
                        }))
                    })).filter(d => d.errors.length > 0);
                }
                case 'search_in_files': {
                    const pattern = input_data.pattern || '';
                    const searchPath = input_data.path || '.';
                    const isRegex = input_data.is_regex || false;
                    
                    // Use VS Code's findTextInFiles API
                    const results: Array<{file: string, line: number, text: string}> = [];
                    const searchPattern = isRegex ? new RegExp(pattern, 'gi') : pattern;
                    
                    // Simple file search using workspace.findFiles and reading content
                    const files = await vscode.workspace.findFiles(
                        searchPath === '.' ? '**/*' : `${searchPath}/**/*`,
                        '**/node_modules/**',
                        100
                    );
                    
                    for (const file of files) {
                        try {
                            const content = await vscode.workspace.fs.readFile(file);
                            const text = new TextDecoder().decode(content);
                            const lines = text.split('\n');
                            
                            lines.forEach((line, idx) => {
                                const matches = isRegex 
                                    ? line.match(searchPattern)
                                    : line.toLowerCase().includes(pattern.toLowerCase());
                                if (matches) {
                                    results.push({
                                        file: vscode.workspace.asRelativePath(file),
                                        line: idx + 1,
                                        text: line.trim().substring(0, 100)
                                    });
                                }
                            });
                        } catch {
                            // Skip files that can't be read
                        }
                        
                        if (results.length >= 50) break; // Limit results
                    }
                    return results;
                }
                case 'get_file_outline': {
                    const path = input_data.path || '';
                    const fileUri = path.startsWith('/') || path.includes(':') 
                        ? vscode.Uri.file(path) 
                        : vscode.Uri.joinPath(workspaceRoot, path);
                    
                    const symbols = await vscode.commands.executeCommand<vscode.DocumentSymbol[]>(
                        'vscode.executeDocumentSymbolProvider',
                        fileUri
                    );
                    
                    if (!symbols) return [];
                    
                    const flattenSymbols = (syms: vscode.DocumentSymbol[], depth = 0): Array<{name: string, kind: string, line: number, depth: number}> => {
                        const result: Array<{name: string, kind: string, line: number, depth: number}> = [];
                        for (const sym of syms) {
                            result.push({
                                name: sym.name,
                                kind: vscode.SymbolKind[sym.kind],
                                line: sym.range.start.line + 1,
                                depth
                            });
                            if (sym.children) {
                                result.push(...flattenSymbols(sym.children, depth + 1));
                            }
                        }
                        return result;
                    };
                    
                    return flattenSymbols(symbols);
                }
                case 'get_workspace_structure': {
                    const maxDepth = input_data.max_depth || 3;
                    const relativePath = input_data.path || '';
                    const baseUri = relativePath 
                        ? vscode.Uri.joinPath(workspaceRoot, relativePath)
                        : workspaceRoot;
                    
                    const buildTree = async (uri: vscode.Uri, depth: number, prefix: string): Promise<string> => {
                        if (depth > maxDepth) return '';
                        
                        try {
                            const entries = await vscode.workspace.fs.readDirectory(uri);
                            const lines: string[] = [];
                            
                            // Sort: directories first, then files
                            entries.sort((a, b) => {
                                if (a[1] === b[1]) return a[0].localeCompare(b[0]);
                                return b[1] - a[1]; // Directories (2) before files (1)
                            });
                            
                            for (const [name, type] of entries) {
                                // Skip common non-essential folders
                                if (['node_modules', '.git', '__pycache__', '.venv', 'dist', 'out', '.next'].includes(name)) {
                                    lines.push(`${prefix}${name}/ (skipped)`);
                                    continue;
                                }
                                
                                if (type === vscode.FileType.Directory) {
                                    lines.push(`${prefix}${name}/`);
                                    const childUri = vscode.Uri.joinPath(uri, name);
                                    const childTree = await buildTree(childUri, depth + 1, prefix + '  ');
                                    if (childTree) lines.push(childTree);
                                } else {
                                    lines.push(`${prefix}${name}`);
                                }
                            }
                            
                            return lines.join('\n');
                        } catch (err) {
                            return `Error reading directory: ${uri.fsPath}`;
                        }
                    };
                    
                    return await buildTree(baseUri, 1, '');
                }
                case 'run_terminal_command': {
                    const command = input_data.command || '';
                    const cwd = input_data.cwd;
                    
                    return new Promise((resolve) => {
                        const workDir = cwd 
                            ? (cwd.startsWith('/') || cwd.includes(':') ? cwd : vscode.Uri.joinPath(workspaceRoot, cwd).fsPath)
                            : workspaceRoot.fsPath;
                        
                        cp.exec(command, { cwd: workDir, timeout: 30000, maxBuffer: 1024 * 1024 }, (error: any, stdout: string, stderr: string) => {
                            resolve({
                                exitCode: error ? error.code || 1 : 0,
                                output: stdout + (stderr ? '\nSTDERR:\n' + stderr : '')
                            });
                        });
                    });
                }
                case 'execute_vscode_command': {
                    const command = input_data.command;
                    const args = input_data.args || [];
                    
                    if (!command) return "Error: No command specified";
                    
                    try {
                        const result = await vscode.commands.executeCommand(command, ...args);
                        return result !== undefined ? result : "Command executed successfully";
                    } catch (err: any) {
                        return `Error executing command ${command}: ${err.message}`;
                    }
                }
                case 'get_workspace_config': {
                    const section = input_data.section;
                    if (!section) return "Error: No section specified";
                    return vscode.workspace.getConfiguration(section);
                }
                case 'update_workspace_config': {
                    const section = input_data.section;
                    const key = input_data.key;
                    const value = input_data.value;
                    const target = input_data.target === 'user' ? vscode.ConfigurationTarget.Global : vscode.ConfigurationTarget.Workspace;
                    
                    if (!section || !key) return "Error: Section and key are required";
                    
                    await vscode.workspace.getConfiguration(section).update(key, value, target);
                    return "Configuration updated";
                }
                case 'find_references': {
                    const symbol = input_data.symbol || '';
                    const filePath = input_data.path;
                    
                    // If we have a file path, try to find the symbol position first
                    const results: Array<{file: string, line: number, text: string}> = [];
                    
                    if (filePath) {
                        const fileUri = filePath.startsWith('/') || filePath.includes(':') 
                            ? vscode.Uri.file(filePath) 
                            : vscode.Uri.joinPath(workspaceRoot, filePath);
                        
                        try {
                            // Get document symbols to find the position
                            const symbols = await vscode.commands.executeCommand<vscode.DocumentSymbol[]>(
                                'vscode.executeDocumentSymbolProvider',
                                fileUri
                            );
                            
                            // Find the symbol position
                            const findSymbolPosition = (syms: vscode.DocumentSymbol[]): vscode.Position | null => {
                                for (const sym of syms) {
                                    if (sym.name === symbol) {
                                        return sym.selectionRange.start;
                                    }
                                    if (sym.children) {
                                        const found = findSymbolPosition(sym.children);
                                        if (found) return found;
                                    }
                                }
                                return null;
                            };
                            
                            const position = symbols ? findSymbolPosition(symbols) : null;
                            
                            if (position) {
                                // Get references using LSP
                                const locations = await vscode.commands.executeCommand<vscode.Location[]>(
                                    'vscode.executeReferenceProvider',
                                    fileUri,
                                    position
                                );
                                
                                if (locations) {
                                    for (const loc of locations.slice(0, 50)) {
                                        const doc = await vscode.workspace.openTextDocument(loc.uri);
                                        const line = doc.lineAt(loc.range.start.line);
                                        results.push({
                                            file: vscode.workspace.asRelativePath(loc.uri),
                                            line: loc.range.start.line + 1,
                                            text: line.text.trim().substring(0, 100)
                                        });
                                    }
                                }
                            }
                        } catch (e) {
                            console.error('Error finding references via LSP:', e);
                        }
                    }
                    
                    // Fallback: text search if LSP didn't find anything
                    if (results.length === 0) {
                        const files = await vscode.workspace.findFiles('**/*', '**/node_modules/**', 200);
                        
                        for (const file of files) {
                            try {
                                const content = await vscode.workspace.fs.readFile(file);
                                const text = new TextDecoder().decode(content);
                                const lines = text.split('\n');
                                
                                lines.forEach((line, idx) => {
                                    // Use word boundary matching
                                    const regex = new RegExp(`\\b${symbol.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`);
                                    if (regex.test(line)) {
                                        results.push({
                                            file: vscode.workspace.asRelativePath(file),
                                            line: idx + 1,
                                            text: line.trim().substring(0, 100)
                                        });
                                    }
                                });
                            } catch {
                                // Skip unreadable files
                            }
                            
                            if (results.length >= 50) break;
                        }
                    }
                    
                    return results;
                }
                default:
                    return `Unknown tool: ${tool_name}`;
            }
        } catch (err: any) {
            return `Error executing ${tool_name}: ${err.message}`;
        }
    }

    private _getHtmlForWebview(webview: vscode.Webview) {
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'dist', 'webview.js'));
        const config = vscode.workspace.getConfiguration('vcca');
        const port = config.get<number>('port') || 8775;
        
        const nonce = getNonce();

        // Allow connection to 127.0.0.1:${port} for WebSocket
        // Allow media-src for TTS playback
        return `<!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} https:; script-src 'nonce-${nonce}'; style-src ${webview.cspSource} 'unsafe-inline'; connect-src 'self' ws://127.0.0.1:${port} http://127.0.0.1:${port} ws://localhost:${port} http://localhost:${port} https://*.vscode-cdn.net https://*.vscode-resource.vscode-cdn.net; media-src 'self' blob: data: mediastream:;">
                <meta http-equiv="Permissions-Policy" content="microphone=*">
                <title>VCCA Chat</title>
                <script nonce="${nonce}">
                    window.VCCA_CONFIG = {
                        port: ${port}
                    };
                </script>
            </head>
            <body>
                <div id="root"></div>
                <script nonce="${nonce}" src="${scriptUri}"></script>
            </body>
            </html>`;
    }
}

function getNonce() {
    let text = '';
    const possible = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
    for (let i = 0; i < 32; i++) {
        text += possible.charAt(Math.floor(Math.random() * possible.length));
    }
    return text;
}
