/**
 * ZHTag 前端（web/js/zhtag.js）桩测试 —— 不需要 ComfyUI。
 *
 *   node comfyui-zh-tag/tests/test_frontend.mjs
 *
 * 原理：搭一个假的目录结构
 *   <tmp>/scripts/app.js                              ← 桩：导出 app
 *   <tmp>/extensions/comfyui-zh-tag/js/zhtag.js       ← 被测文件（原样复制）
 * 这样脚本里的 import { app } from "../../scripts/app.js" 就能真的解析到桩上。
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const HERE = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1'));
const PLUGIN = path.dirname(HERE);

let pass = 0, fail = 0;
const ok = (cond, label, extra = '') => {
    if (cond) { pass++; console.log('  ✓ ' + label + (extra ? '  ' + extra : '')); }
    else { fail++; console.log('  ✗ ' + label + '  ' + extra); }
};
const tick = (ms = 10) => new Promise((r) => setTimeout(r, ms));

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'zhtag-fe-'));
const appStubPath = path.join(tmp, 'scripts', 'app.js');
const jsDir = path.join(tmp, 'extensions', 'comfyui-zh-tag', 'js');
fs.mkdirSync(path.dirname(appStubPath), { recursive: true });
fs.mkdirSync(jsDir, { recursive: true });

fs.writeFileSync(appStubPath, `
export const app = {
  _ext: null, _toasts: [], _settings: {
    'ZHTag.auto': true, 'ZHTag.trigger': 'blur', 'ZHTag.idleMs': 900,
    'ZHTag.unknownMode': 'drop', 'ZHTag.normalize': true,
    'ZHTag.fallback': false, 'ZHTag.showToast': false,
  },
  registerExtension(e) { this._ext = e; return e; },
  ui: { settings: { getSettingValue(id) { return app._settings[id]; } } },
  extensionManager: { toast: { add(o) { app._toasts.push(o); } } },
  graph: { setDirtyCanvas() {} },
  canvas: { selected_nodes: {} },
};
`);
fs.copyFileSync(path.join(PLUGIN, 'web', 'js', 'zhtag.js'), path.join(jsDir, 'zhtag.js'));

// ---- 浏览器环境桩 ----
const fetchCalls = [];
const winListeners = {};
globalThis.window = { addEventListener: (t, fn) => { winListeners[t] = fn; }, comfyAPI: undefined };
globalThis.document = { querySelector: () => null, addEventListener: () => {} };
globalThis.fetch = async (url, opts) => {
    fetchCalls.push({ url, body: JSON.parse(opts.body) });
    return {
        ok: true,
        json: async () => ({
            ok: true,
            english: 'twintails, girl, smile',
            info: '命中 3 / 兜底 0 / 词库 3640',
        }),
    };
};

const mod = await import(pathToFileURL(path.join(jsDir, 'zhtag.js')).href);
const { app } = await import(pathToFileURL(appStubPath).href);

console.log('\n[1] 注册与设置');
const ext = app._ext;
ok(!!ext && ext.name === 'ZHTag', 'registerExtension 被调用且名字正确', ext ? ext.name : '(无)');
ok(Array.isArray(ext.settings) && ext.settings.length === 7, '声明了 7 项设置', String(ext.settings?.length));
ok(ext.settings.every((s) => s && typeof s === 'object' && s.id && s.name && s.type && 'defaultValue' in s),
    '设置项都不是 undefined（新版前端会因此报错）',
    ext.settings.map((s) => (s && s.id) || 'undefined').join(','));
ok(ext.settings.some((s) => s.id === 'ZHTag.unknownMode' && s.type === 'combo'
    && Array.isArray(s.options) && s.options.join() === 'drop,keep,fallback'),
    '有「词典没查到的词怎么办」下拉（drop/keep/fallback）');
ok(ext.settings.some((s) => s.id === 'ZHTag.normalize' && s.type === 'boolean'),
    '有「Danbooru 规范化并排序」开关');
ok(typeof ext.setup === 'function' && typeof ext.nodeCreated === 'function'
    && typeof ext.beforeRegisterNodeDef === 'function', '三个钩子都在');

console.log('\n[2] 文本框失焦自动翻译');
const listeners = {};
const el = { addEventListener: (t, fn) => { listeners[t] = fn; } };
let callbackCalls = 0;
const widget = {
    name: 'text', type: 'customtext', value: '双马尾女孩微笑',
    options: { multiline: true }, inputEl: el, callback: () => { callbackCalls++; },
};
const dirty = { n: 0 };
app.graph.setDirtyCanvas = () => { dirty.n++; };
const node = { widgets: [widget], onWidgetChanged: () => {} };

ext.nodeCreated(node);
ok(typeof listeners.blur === 'function', '已给真实 textarea 绑上 blur（widget.inputEl 存在时）');
ok(!!widget._zht_hooked, 'widget 标记为已挂钩（避免重复包装）');

listeners.blur();
await tick(30);
ok(fetchCalls.length === 1 && fetchCalls[0].url === '/zhtag/translate', '失焦后调用了 /zhtag/translate');
ok(fetchCalls[0]?.body?.text === '双马尾女孩微笑' && fetchCalls[0]?.body?.mode === 'tags', '请求带了 text 与 mode', JSON.stringify(fetchCalls[0]?.body));
ok(fetchCalls[0]?.body?.unknownMode === 'drop', '默认未命中处理 = drop', String(fetchCalls[0]?.body?.unknownMode));
ok(fetchCalls[0]?.body?.normalize === true, '默认开启 Danbooru 规范化', String(fetchCalls[0]?.body?.normalize));
ok(widget.value === 'twintails, girl, smile', '翻译结果写回了文本框', widget.value);
ok(dirty.n > 0, '画布被标脏（界面会刷新）');

console.log('\n[3] 不重复翻译 / 纯英文不动');
listeners.blur();
await tick(30);
ok(fetchCalls.length === 1, '内容没变时不再请求');
widget.value = 'masterpiece, best quality';
listeners.blur();
await tick(30);
ok(fetchCalls.length === 1, '纯英文不会触发翻译');

console.log('\n[4] 节点右键菜单');
const nodeType = { prototype: {} };
await ext.beforeRegisterNodeDef(nodeType, {});
const options = [];
const ret = nodeType.prototype.getExtraMenuOptions.call(node, null, options);
ok(typeof nodeType.prototype.getExtraMenuOptions === 'function', 'getExtraMenuOptions 已被包装', String(ret === undefined));
ok(options.length >= 2, '注入了菜单项', options.map((o) => o.content).join(' / '));
ok(options.some((o) => /中文Tag→英文/.test(o.content)), '有「中文Tag→英文」');
ok(options.some((o) => /词库状态/.test(o.content)), '有「查看词库状态」');
ok(options.some((o) => /下载\/更新社区词典/.test(o.content)), '有「下载/更新社区词典」');
widget.value = '再翻一次给我看';
const beforeMenu = fetchCalls.length;
options.find((o) => /中文Tag→英文/.test(o.content)).callback();
await tick(30);
ok(fetchCalls.length === beforeMenu + 1, '菜单点击会翻译该节点的文本框', `请求数 ${fetchCalls.length}`);

console.log('\n[5] 快捷键 Ctrl+Alt+T（翻选中节点）');
const w2 = { name: 'text', type: 'customtext', value: '樱花树下的女孩', options: { multiline: true }, callback: () => {} };
const n2 = { widgets: [w2], onWidgetChanged: () => {} };
ext.nodeCreated(n2);
app.canvas.selected_nodes = { 1: n2 };
const before = fetchCalls.length;
winListeners.keydown?.({ ctrlKey: true, altKey: true, key: 'T', preventDefault() {} });
await tick(30);
ok(fetchCalls.length === before + 1, '快捷键触发了翻译', `请求数 ${fetchCalls.length}`);
ok(w2.value === 'twintails, girl, smile', '选中节点的文本框被翻译', w2.value);
app.canvas.selected_nodes = {};

console.log('\n[6] 兜底开关随设置变化');
app._settings['ZHTag.fallback'] = true;
const w3 = { name: 'text', type: 'customtext', value: '未知词', options: { multiline: true }, callback: () => {} };
ext.nodeCreated({ widgets: [w3] });
// 直接调内部翻译入口（window.ZHTag 暴露的）
await globalThis.window.ZHTag?.translateText('测试');
ok(fetchCalls[fetchCalls.length - 1]?.body?.fallback === true, '设置打开后请求里带 fallback=true',
    JSON.stringify(fetchCalls[fetchCalls.length - 1]?.body));

console.log('\n[7] 未命中处理与规范化随设置变化');
app._settings['ZHTag.unknownMode'] = 'keep';
app._settings['ZHTag.normalize'] = false;
await globalThis.window.ZHTag?.translateText('测试');
let last = fetchCalls[fetchCalls.length - 1]?.body;
ok(last?.unknownMode === 'keep' && last?.normalize === false,
    '改成 keep / 关掉规范化后请求同步变化', JSON.stringify(last));
app._settings['ZHTag.unknownMode'] = 'drop';
app._settings['ZHTag.normalize'] = true;

console.log('\n[8] 右键菜单里的「下载/更新社区词典」');
const dlItem = options.find((o) => /下载\/更新社区词典/.test(o.content));
const beforeDl = fetchCalls.length;
await dlItem.callback();
await tick(30);
ok(fetchCalls.length === beforeDl + 1 && fetchCalls[beforeDl].url === '/zhtag/dict/download',
    '点了就 POST /zhtag/dict/download', String(fetchCalls[beforeDl]?.url));
ok(app._toasts.length > 0, '结果通过 toast 反馈给用户', app._toasts[app._toasts.length - 1]?.summary || '');

fs.rmSync(tmp, { recursive: true, force: true });
console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
process.exit(fail ? 1 : 0);
