const { spawn } = require('child_process');
const PROXY = 'http://127.0.0.1:7897';
class McpClient {
  constructor(opts = {}) {
    const env = { ...process.env,
      HTTP_PROXY: PROXY, HTTPS_PROXY: PROXY,
      npm_config_proxy: PROXY, npm_config_https_proxy: PROXY,
      PLAYWRIGHT_MCP_PROXY_SERVER: PROXY, PLAYWRIGHT_MCP_BROWSER: 'chromium',
    };
    if (opts.headless) env.PLAYWRIGHT_MCP_HEADLESS = 'true';
    // Each crawler worker needs its own in-memory browser profile. Without
    // --isolated, concurrent MCP processes contend for the same persistent
    // profile and silently turn an entire shard into "Browser is already in use" errors.
    this.child = spawn('npx.cmd', ['-y', '@playwright/mcp@latest', '--isolated'], { env, shell: true });
    this.buf = ''; this.idc = 0; this.pending = {}; this.closed = false;
    this.timeoutMs = Number(opts.timeoutMs || 90000);
    this.child.stdout.on('data', d => this._onData(d));
    this.child.stderr.on('data', d => { const s = d.toString(); if (/error|fail|executable/i.test(s)) process.stderr.write('[mcp-stderr] ' + s); });
    this.child.on('exit', () => { this.closed = true; });
  }
  _onData(d) { this.buf += d.toString(); let idx; while ((idx = this.buf.indexOf('\n')) >= 0) { const line = this.buf.slice(0, idx); this.buf = this.buf.slice(idx + 1); if (!line.trim()) continue; try { const m = JSON.parse(line); if (m.id && this.pending[m.id]) { const p = this.pending[m.id]; delete this.pending[m.id]; if (m.error) p.rej(new Error((m.error && m.error.message) || JSON.stringify(m.error))); else p.res(m.result); } } catch (e) {} } }
  _send(method, params, timeoutMs = this.timeoutMs) { if (this.closed) return Promise.reject(new Error('closed')); const id = ++this.idc; return new Promise((res, rej) => { const timer = setTimeout(() => { if (!this.pending[id]) return; delete this.pending[id]; rej(new Error(method + ' timed out after ' + timeoutMs + 'ms')); }, timeoutMs); this.pending[id] = { res: value => { clearTimeout(timer); res(value); }, rej: error => { clearTimeout(timer); rej(error); } }; this.child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n'); }); }
  async init() { const r = await this._send('initialize', { protocolVersion: '2024-11-05', capabilities: {}, clientInfo: { name: 'rs', version: '1' } }); this.child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n'); return r; }
  call(name, args) { return this._send('tools/call', { name, arguments: args || {} }); }
  static text(result) { if (!result) return ''; if (result.isError) throw new Error('tool error: ' + (result.content || []).map(x => x.text || '').join('\n')); return (result.content || []).map(x => x.text || '').join('\n'); }
  async navigate(url) { return this.call('browser_navigate', { url }); }
  async waitFor(time) { return this.call('browser_wait_for', { time }); }
  async eval(fn) { const r = await this.call('browser_evaluate', { function: fn }); return McpClient.text(r); }
  async close() { try { await this._send('tools/call', { name: 'browser_close', arguments: {} }, 5000); } catch (e) {} this.closed = true; for (const id of Object.keys(this.pending)) { try { this.pending[id].rej(new Error('client closed')); } catch (e) {} delete this.pending[id]; } try { this.child.stdin.end(); } catch (e) {} try { this.child.kill(); } catch (e) {} }
}
module.exports = { McpClient };
