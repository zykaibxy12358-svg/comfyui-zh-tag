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
    'ZHTag.complete': true, 'ZHTag.completeOnline': true, 'ZHTag.completeLimit': 10,
  },
  registerExtension(e) { this._ext = e; return e; },
  ui: { settings: { getSettingValue(id) { return app._settings[id]; } } },
  extensionManager: { toast: { add(o) { app._toasts.push(o); } } },
  graph: { setDirtyCanvas() {} },
  canvas: { selected_nodes: {} },
};
`);
fs.copyFileSync(path.join(PLUGIN, 'web', 'js', 'zhtag.js'), path.join(jsDir, 'zhtag.js'));

// ---- 极简 DOM 桩（IDE 式补全弹层要用） ----
class FakeEl {
    constructor(tag) {
        this.tagName = tag; this.children = []; this.parentNode = null;
        this.style = {}; this.dataset = {}; this.className = '';
        this._text = ''; this.listeners = {};
        this.offsetWidth = 220; this.offsetHeight = 150; this.clientWidth = 300; this.clientHeight = 120;
        this.scrollLeft = 0; this.scrollTop = 0; this.value = ''; this.selectionStart = 0; this.selectionEnd = 0;
    }
    get textContent() { return this._text; }
    set textContent(v) { this._text = String(v); this.children = []; }
    get classList() {
        const self = this;
        const list = () => String(self.className).split(/\s+/).filter(Boolean);
        const set = (arr) => { self.className = arr.join(' '); };
        return {
            contains: (c) => list().includes(c),
            add: (c) => { if (!list().includes(c)) set([...list(), c]); },
            remove: (c) => set(list().filter((x) => x !== c)),
            toggle: (c, on) => {
                const has = list().includes(c);
                const want = on === undefined ? !has : !!on;
                if (want && !has) set([...list(), c]);
                if (!want && has) set(list().filter((x) => x !== c));
            },
        };
    }
    appendChild(c) { this.children.push(c); c.parentNode = this; return c; }
    removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; }
    remove() { this.parentNode?.removeChild?.(this); }
    contains(c) { return this.children.includes(c) || this.children.some((k) => k.contains?.(c)); }
    addEventListener(t, fn) { (this.listeners[t] ||= []).push(fn); }
    dispatch(t, e = {}) { (this.listeners[t] || []).forEach((fn) => fn(e)); }
    getBoundingClientRect() { return { left: 100, top: 200, right: 260, bottom: 216, width: 160, height: 16 }; }
    scrollIntoView() {}
    focus() { globalThis.document.activeElement = this; }
    closest(sel) {
        const classes = String(sel).split('.').filter(Boolean);
        let n = this;
        while (n) {
            if (classes.every((k) => n.classList.contains(k))) return n;
            n = n.parentNode;
        }
        return null;
    }
    querySelectorAll(sel) {
        const classes = String(sel).split('.').filter(Boolean);
        const out = [];
        const walk = (n) => {
            for (const c of n.children) {
                if (classes.every((k) => c.classList.contains(k))) out.push(c);
                walk(c);
            }
        };
        walk(this);
        return out;
    }
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

const fakeBody = new FakeEl('body');
const fakeHead = new FakeEl('head');
globalThis.document = {
    body: fakeBody, head: fakeHead, activeElement: null,
    createElement: (tag) => new FakeEl(tag),
    querySelector: () => null,
    addEventListener: () => {},
};
globalThis.getComputedStyle = () => ({
    fontFamily: 'monospace', fontSize: '13px', fontWeight: '400', fontStyle: 'normal',
    letterSpacing: 'normal', lineHeight: '16px', textTransform: 'none', textIndent: '0px',
    paddingTop: '4px', paddingRight: '4px', paddingBottom: '4px', paddingLeft: '4px',
    borderTopWidth: '1px', borderRightWidth: '1px', borderBottomWidth: '1px', borderLeftWidth: '1px',
    boxSizing: 'border-box', tabSize: '4',
});

// ---- 浏览器环境桩 ----
const fetchCalls = [];
const winListeners = {};
let completeResults = [];
let translatorMode = 'llm';       // 后端兜底翻译配置：keep（没配）/ llm / google
globalThis.window = {
    addEventListener: (t, fn) => { winListeners[t] = fn; },
    comfyAPI: undefined, innerWidth: 1280, innerHeight: 800,
};
globalThis.fetch = async (url, opts) => {
    fetchCalls.push({ url, method: opts?.method || 'GET', body: opts?.body ? JSON.parse(opts.body) : null });
    if (String(url).startsWith('/zhtag/complete')) {
        return { ok: true, json: async () => ({ ok: true, results: completeResults }) };
    }
    if (String(url).startsWith('/zhtag/status')) {
        return {
            ok: true,
            json: async () => ({
                ok: true, entries: 3955, index: 31171, sources: ['zh_tags.csv'],
                translator: { fallback: translatorMode, cached: 0, model: translatorMode === 'llm' ? 'qwen2.5:7b' : null },
            }),
        };
    }
    return {
        ok: true,
        json: async () => ({
            ok: true,
            english: 'twintails, girl, smile',
            info: '命中 3 / 兜底 0 / 词库 3955',
        }),
    };
};

const mod = await import(pathToFileURL(path.join(jsDir, 'zhtag.js')).href);
const { app } = await import(pathToFileURL(appStubPath).href);

console.log('\n[1] 注册与设置');
const ext = app._ext;
ok(!!ext && ext.name === 'ZHTag', 'registerExtension 被调用且名字正确', ext ? ext.name : '(无)');
ok(Array.isArray(ext.settings) && ext.settings.length === 10, '声明了 10 项设置', String(ext.settings?.length));
ok(ext.settings.some((s) => s.id === 'ZHTag.complete' && s.type === 'boolean')
    && ext.settings.some((s) => s.id === 'ZHTag.completeOnline' && s.type === 'boolean')
    && ext.settings.some((s) => s.id === 'ZHTag.completeLimit' && s.type === 'number'),
    '有 IDE 式补全的三个设置（开关/联网/候选数量）');
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

console.log('\n[9] IDE 式补全：片段识别与触发条件');
const Z = globalThis.window.ZHTag;
ok(typeof Z?.openCompletion === 'function' && typeof Z?.handleCompletionKey === 'function',
    '补全相关入口已暴露（供测试/高级用法）');
ok(Z.fragmentAt({ value: 'skirt, lanfa', selectionStart: 12 }).text === 'lanfa',
    '「, 」后面的空格不算片段', Z.fragmentAt({ value: 'skirt, lanfa', selectionStart: 12 }).text);
ok(Z.fragmentAt({ value: '1girl, 蓝发', selectionStart: 9 }).text === '蓝发', '中文片段');
ok(Z.fragmentAt({ value: '(蓝发:1.2)', selectionStart: 7 }).text === '1.2',
    '括号权重里的数字单独成片段（不会去补全中文）', Z.fragmentAt({ value: '(蓝发:1.2)', selectionStart: 7 }).text);
ok(Z.fragmentAt({ value: '1girl, blue hair, long', selectionStart: 23 }).text === 'long', '英文片段');
ok(Z.wantCompletion('蓝') && Z.wantCompletion('lf') && Z.wantCompletion('shuangmawei'),
    '中文 1 个字 / 拼音 2 个字母以上就触发');
ok(!Z.wantCompletion('l') && !Z.wantCompletion('  ') && !Z.wantCompletion('1'),
    '单个字母或空白不触发（避免打字时一直弹）');

console.log('\n[10] IDE 式补全：弹层、键盘选择与替换');
completeResults = [
    { en: 'blue hair', zh: '蓝发', score: 95, count: 855605, kind: 'pinyin' },
    { en: 'blue eyes', zh: '蓝眼睛', score: 70, count: 41233, kind: 'pinyin' },
];
const ta = new FakeEl('textarea');
ta.value = 'skirt, lanfa';
ta.selectionStart = ta.selectionEnd = 12;
const wc = { name: 'text', type: 'customtext', value: ta.value, options: { multiline: true }, inputEl: ta, callback: () => {} };
const nc = { widgets: [wc], onWidgetChanged: () => {} };
const beforeC = fetchCalls.length;
await Z.openCompletion(nc, wc, ta);
await tick(30);
const cmpReq = fetchCalls.slice(beforeC).find((c) => String(c.url).startsWith('/zhtag/complete'));
ok(!!cmpReq && cmpReq.url === '/zhtag/complete?q=lanfa&limit=10', '按片段发起补全查询', String(cmpReq?.url));
const pop = Z.getPopupEl();
ok(!!pop && pop.style.display === 'block', '候选框显示出来了');
const rows = pop.querySelectorAll('.zht-row');
ok(rows.length === 2, '渲染出候选行', String(rows.length));
ok(rows[0].children[0].textContent === 'blue hair' && rows[0].children[1].textContent.includes('蓝发'),
    '第一行是英文 tag + 来源中文', `${rows[0].children[0].textContent} / ${rows[0].children[1].textContent}`);
ok(rows[0].children[2].textContent === '856k', '显示 Danbooru 热度', rows[0].children[2].textContent);
ok(Z.getPopupState().index === 0 && rows[0].classList.contains('on'), '默认选中第一行');

const key = (k) => ({ key: k, isComposing: false, preventDefault() {}, stopPropagation() {} });
ok(Z.handleCompletionKey(key('ArrowDown'), nc, wc, ta) === true, '↓ 被补全框吃掉（不会跑去做别的事）');
ok(Z.getPopupState().index === 1, '↓ 选中第二行');
ok(Z.handleCompletionKey(key('ArrowUp'), nc, wc, ta) === true && Z.getPopupState().index === 0, '↑ 回到第一行');
Z.handleCompletionKey(key('Enter'), nc, wc, ta);
ok(ta.value === 'skirt, blue hair, ', 'Enter 把拼音片段换成英文 tag 并补好分隔', JSON.stringify(ta.value));
ok(wc.value === 'skirt, blue hair, ', '节点上的值同步更新', JSON.stringify(wc.value));
ok(Z.getPopupState() === null && pop.style.display === 'none', '采用后候选框自动关闭');

console.log('\n[11] IDE 式补全：Esc 关闭 / 鼠标点选 / 中文输入');
ta.value = '蓝发';
ta.selectionStart = ta.selectionEnd = 2;
await Z.openCompletion(nc, wc, ta);
await tick(30);
ok(Z.getPopupState()?.q === '蓝发', '中文也能作为查询词', Z.getPopupState()?.q);
Z.handleCompletionKey(key('Escape'), nc, wc, ta);
ok(Z.getPopupState() === null, 'Esc 关掉候选框');
await Z.openCompletion(nc, wc, ta);
await tick(30);
const rows2 = Z.getPopupEl().querySelectorAll('.zht-row');
ok(rows2.length === 2, '重新打开后候选行还在', String(rows2.length));
// 真实浏览器里 mousedown 会冒泡到弹层，这里手动指定 target 复刻
Z.getPopupEl().dispatch('mousedown', { target: rows2[1], preventDefault() {}, stopPropagation() {} });
ok(ta.value === 'blue eyes, ', '鼠标点第二行 → 中文被替换成对应英文', JSON.stringify(ta.value));
ok(Z.getPopupState() === null, '点选后关闭');

console.log('\n[12] IDE 式补全：词库没有时给「在线翻译」一行');
await Z.refreshTranslatorStatus();
ok(Z.translatorReady() === true, '读到后端兜底翻译配置（llm）→ 在线翻译可用');
completeResults = [];
ta.value = 'qianzi';
ta.selectionStart = ta.selectionEnd = 6;
await Z.openCompletion(nc, wc, ta);
await tick(30);
ok(Z.getPopupState()?.rows.length === 0, '本地没有候选时先不显示候选框');
await tick(600);                       // 等在线翻译那一步
const onlineRows = Z.getPopupState()?.rows || [];
ok(onlineRows.some((r) => r.kind === 'online'), '本地没有 → 自动补上「在线翻译」候选',
    JSON.stringify(onlineRows.map((r) => r.en)));
const onlineReq = fetchCalls.slice(-5).find((c) => c.url === '/zhtag/translate');
ok(onlineReq?.body?.fallback === true && onlineReq?.body?.unknownMode === 'fallback',
    '在线翻译走的是兜底链路', JSON.stringify(onlineReq?.body));
Z.closePopup();
// 关掉联网开关后不再请求
app._settings['ZHTag.completeOnline'] = false;
completeResults = [];
const beforeOffline = fetchCalls.length;
ta.value = 'qianzi';
await Z.openCompletion(nc, wc, ta);
await tick(700);
ok(!fetchCalls.slice(beforeOffline).some((c) => c.url === '/zhtag/translate'),
    '关掉「在线翻译」后一个网络请求都不发', String(fetchCalls.length - beforeOffline));
app._settings['ZHTag.completeOnline'] = true;

console.log('\n[13] IDE 式补全：没配在线翻译时给可点的提示行（不静默失败）');
translatorMode = 'keep';
await Z.refreshTranslatorStatus();
ok(Z.translatorReady() === false, 'keep = 没配在线翻译');
completeResults = [];
ta.value = 'qianziwoya';
ta.selectionStart = ta.selectionEnd = 10;
const beforeHint = fetchCalls.length;
await Z.openCompletion(nc, wc, ta);
await tick(700);
const hintRows = Z.getPopupState()?.rows || [];
ok(hintRows.some((r) => r.kind === 'hint'), '给出「在线翻译未配置」提示行',
    JSON.stringify(hintRows.map((r) => r.kind)));
ok(!fetchCalls.slice(beforeHint).some((c) => c.url === '/zhtag/translate'),
    '没配就不发翻译请求（不浪费你的时间）');
const toastsBefore = app._toasts.length;
const textBefore = ta.value;
Z.commitRow(0);
ok(app._toasts.length > toastsBefore
    && /config\.json/.test(app._toasts[app._toasts.length - 1]?.detail || ''),
    '点提示行 → 告诉用户去 config.json 里开', app._toasts[app._toasts.length - 1]?.detail?.slice(0, 40));
ok(ta.value === textBefore, '提示行不会被写进文本框', JSON.stringify(ta.value));
translatorMode = 'llm';

fs.rmSync(tmp, { recursive: true, force: true });
console.log(`\n结果：${pass} 通过 / ${fail} 失败`);
process.exit(fail ? 1 : 0);
