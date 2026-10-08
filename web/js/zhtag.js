/**
 * ZHTag 前端扩展（v1.2）：
 *
 * · IDE 式补全（默认）：文本框里打中文或拼音 → 光标下方弹出英文 tag 候选，
 *   ↑↓ 选、Enter/Tab 确认、Esc 关掉；词库没有的词显示「在线翻译」一行。
 * · 整句翻译：失焦时自动翻（可选「停顿后」），或用右键菜单 / Ctrl+Alt+T 手动翻。
 * · 所有文本输入框通用（CLIPTextEncode 与 ZHTag 节点都在内）。
 *
 * 只用到公开 API（app.registerExtension / nodeCreated / getExtraMenuOptions / settings），
 * 并对缺 API 的老版本做了降级保护；DOM 相关操作全部 try/catch，坏了也不影响出图。
 */
import { app } from "../../../scripts/app.js";

const PLUGIN = "ZHTag";
const CJK = /[\u3400-\u9fff\uf900-\ufaff]/;
const log = (...a) => console.log(`[${PLUGIN}]`, ...a);

const DEFAULTS = {
    auto: true,
    trigger: "blur", // blur | idle | off
    idleMs: 900,
    unknownMode: "drop", // drop | keep | fallback
    normalize: true,
    fallback: false, // 是否让后端走兜底翻译（LLM/在线）
    showToast: true,
    complete: true, // IDE 式补全开关
    completeOnline: true, // 词库里没有时联网翻译
    completeLimit: 10,
};

function setting(id, name, type, defaultValue, extra = {}) {
    // 注意：这里只构造设置对象，由 ComfyUI 的 registerExtension({settings}) 负责注册。
    // 不要再自己调 addSetting——新版前端对 undefined 元素不宽容。
    return { id, name, type, defaultValue, ...extra };
}

function getSetting(id) {
    try {
        const v = app.ui?.settings?.getSettingValue?.(id);
        return v === undefined ? DEFAULTS[id.replace(`${PLUGIN}.`, "")] : v;
    } catch (e) {
        return DEFAULTS[id.replace(`${PLUGIN}.`, "")];
    }
}

const S = (k) => getSetting(`${PLUGIN}.${k}`);

function toast(summary, detail, force = false) {
    // force=true 用于用户主动点菜单触发的操作：结果必须给反馈，不受「翻译后弹提示」开关影响
    if (!force && !S("showToast")) return;
    try {
        app.extensionManager?.toast?.add?.({ severity: "info", summary, detail, life: 3000 });
    } catch (e) {
        /* 没有 toast 就算了 */
    }
}

async function translateText(text) {
    const res = await fetch("/zhtag/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            text,
            mode: "tags",
            fallback: !!S("fallback"),
            unknownMode: String(S("unknownMode") || "drop"),
            normalize: S("normalize") !== false,
        }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return await res.json();
}

/* =====================================================================
 * IDE 式补全：打中文或拼音 → 光标下方列出英文 tag 候选
 * ===================================================================== */

const SUGGEST_DEBOUNCE = 70;      // 打字到发请求的等待（毫秒）
const ONLINE_DEBOUNCE = 450;      // 本地词库没有时，等这么久再联网（避免打一个字就联网）
const FRAG_RE = /[^,，、;；:|：\n\r\t()（）\[\]{}<>]+$/;   // 光标前的「当前片段」（: 也算分隔，权重里也能补全）

let POPUP = null;                 // 单例弹层元素
let STATE = null;                 // {el, widget, node, frag, rows, index, seq}
const onlineCache = new Map();    // 片段 → 在线翻译结果
let TRANSLATOR = null;            // 后端兜底翻译配置（keep/llm/google），用于判断「在线翻译」能不能用

const HINT_UNCONFIGURED = "在线翻译未配置 —— 点这里看怎么开";
const HINT_TEXT = "编辑 custom_nodes/comfyui-zh-tag/data/user/config.json，把 fallback 改成 "
    + "\"llm\"（本地 Ollama/LM Studio，填 base_url+model）或 \"google\"（免 key 在线端点），"
    + "改完重启 ComfyUI 或刷新页面即可。";

const fmtCount = (n) => (!n ? "" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M"
    : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(n));

function fragmentAt(el) {
    const value = String(el?.value ?? "");
    const pos = typeof el?.selectionStart === "number" ? el.selectionStart : value.length;
    const before = value.slice(0, pos);
    const m = before.match(FRAG_RE);
    let text = m ? m[0] : "";
    const lead = (text.match(/^[ \t]*/) || [""])[0].length;   // 「, 蓝发」里的空格不算片段
    if (lead) text = text.slice(lead);
    return { text, start: pos - text.length, end: pos, pos };
}

/** 该不该为这个片段弹候选框 */
function wantCompletion(text) {
    const t = (text || "").trim();
    if (!t) return false;
    if (CJK.test(t)) return true;                       // 中文：一个词就开始给
    if (/^[A-Za-z0-9_]+$/.test(t)) return t.length >= 2; // 拼音/英文：至少两个字符
    return false;
}

function ensurePopup() {
    if (POPUP || typeof document === "undefined" || !document.body) return POPUP;
    const style = document.createElement("style");
    style.textContent = `
.zht-pop{position:fixed;z-index:100000;min-width:200px;max-width:520px;max-height:280px;overflow-y:auto;
  background:#1b1b1f;color:#e8e8ec;border:1px solid #3a3a44;border-radius:6px;
  box-shadow:0 8px 24px rgba(0,0,0,.45);font-size:12px;line-height:1.5;padding:3px 0;
  font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.zht-pop .zht-row{display:flex;gap:8px;align-items:baseline;padding:3px 10px;cursor:pointer;white-space:nowrap}
.zht-pop .zht-row.on{background:#2f6fd0;color:#fff}
.zht-pop .zht-en{font-weight:600;flex:1 1 auto;overflow:hidden;text-overflow:ellipsis}
.zht-pop .zht-src{opacity:.65;font-size:11px;flex:0 0 auto;max-width:190px;overflow:hidden;text-overflow:ellipsis}
.zht-pop .zht-cnt{opacity:.5;font-size:11px;flex:0 0 auto}
.zht-pop .zht-head{padding:2px 10px 3px;font-size:11px;opacity:.5;border-bottom:1px solid #33333c}
.zht-pop .zht-online{color:#8fd3ff}
`;
    try { document.head?.appendChild(style); } catch (e) { /* ignore */ }
    POPUP = document.createElement("div");
    POPUP.className = "zht-pop";
    POPUP.style.display = "none";
    // 用 mousedown 而不是 click：preventDefault 保住文本框焦点
    POPUP.addEventListener("mousedown", (e) => {
        const row = e.target?.closest?.(".zht-row");
        if (!row) return;
        e.preventDefault();
        e.stopPropagation();
        commitRow(Number(row.dataset.i || 0));
    });
    try { document.body.appendChild(POPUP); } catch (e) { /* ignore */ }
    return POPUP;
}

function closePopup() {
    if (POPUP) POPUP.style.display = "none";
    STATE = null;
}

/** textarea 里光标的屏幕坐标（镜像 div 量位置，唯一可靠的做法） */
function caretXY(el, pos) {
    try {
        const cs = getComputedStyle(el);
        const mirror = document.createElement("div");
        const copy = ["fontFamily", "fontSize", "fontWeight", "fontStyle", "letterSpacing", "lineHeight",
            "textTransform", "textIndent", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
            "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth", "boxSizing", "tabSize"];
        for (const p of copy) mirror.style[p] = cs[p];
        mirror.style.position = "fixed";
        mirror.style.top = "0px";
        mirror.style.left = "-99999px";
        mirror.style.width = (el.clientWidth || el.offsetWidth || 200) + "px";
        mirror.style.whiteSpace = "pre-wrap";
        mirror.style.overflowWrap = "break-word";
        mirror.style.visibility = "hidden";
        mirror.textContent = String(el.value).slice(0, pos);
        const marker = document.createElement("span");
        marker.textContent = "\u200b";
        mirror.appendChild(marker);
        document.body.appendChild(mirror);
        const mr = mirror.getBoundingClientRect();
        const kr = marker.getBoundingClientRect();
        const er = el.getBoundingClientRect();
        const lh = parseFloat(cs.lineHeight) || (parseFloat(cs.fontSize) || 13) * 1.35;
        document.body.removeChild(mirror);
        return {
            x: er.left + (kr.left - mr.left) - (el.scrollLeft || 0),
            y: er.top + (kr.top - mr.top) - (el.scrollTop || 0),
            lineHeight: lh,
        };
    } catch (e) {
        const er = el.getBoundingClientRect?.() || { left: 100, top: 100 };
        return { x: er.left, y: er.top, lineHeight: 16 };
    }
}

function renderPopup() {
    if (!POPUP || !STATE) return;
    const rows = STATE.rows;
    POPUP.textContent = "";
    const head = document.createElement("div");
    head.className = "zht-head";
    head.textContent = `ZHTag 补全 · ↑↓ 选择 · Enter 采用 · Esc 关闭`;
    POPUP.appendChild(head);
    rows.forEach((r, i) => {
        const row = document.createElement("div");
        row.className = "zht-row" + (i === STATE.index ? " on" : "") + (r.kind === "online" ? " zht-online" : "");
        row.dataset.i = String(i);
        const en = document.createElement("span");
        en.className = "zht-en";
        en.textContent = r.kind === "online" ? `在线翻译 → ${r.en}` : r.en;
        const src = document.createElement("span");
        src.className = "zht-src";
        src.textContent = r.zh ? `${r.zh}${r.kind === "pinyin" ? " · 拼音" : ""}` : (r.kind === "en" ? "英文标签" : "");
        const cnt = document.createElement("span");
        cnt.className = "zht-cnt";
        cnt.textContent = fmtCount(r.count);
        row.appendChild(en);
        row.appendChild(src);
        row.appendChild(cnt);
        row.addEventListener("mousemove", () => {
            if (!STATE) return;
            STATE.index = i;
            renderSelection();
        });
        POPUP.appendChild(row);
    });
    placePopup();
    POPUP.style.display = "block";
}

function renderSelection() {
    if (!POPUP || !STATE) return;
    [...POPUP.querySelectorAll(".zht-row")].forEach((el, i) => {
        el.classList.toggle("on", i === STATE.index);
    });
    try {
        const on = POPUP.querySelector(".zht-row.on");
        on?.scrollIntoView?.({ block: "nearest" });
    } catch (e) { /* ignore */ }
}

function placePopup() {
    try {
        const { el, frag } = STATE;
        const { x, y, lineHeight } = caretXY(el, frag.pos);
        POPUP.style.left = "0px";
        POPUP.style.top = "0px";
        const w = POPUP.offsetWidth || 240;
        const h = POPUP.offsetHeight || 160;
        const vw = window.innerWidth || 1280;
        const vh = window.innerHeight || 800;
        let left = Math.max(8, Math.min(x, vw - w - 8));
        let top = y + lineHeight + 4;
        if (top + h > vh - 8) top = Math.max(8, y - h - 4);
        POPUP.style.left = left + "px";
        POPUP.style.top = top + "px";
    } catch (e) { /* ignore */ }
}

async function fetchCompletions(q, limit) {
    const res = await fetch(`/zhtag/complete?q=${encodeURIComponent(q)}&limit=${limit}`);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    return Array.isArray(data?.results) ? data.results : [];
}

async function fetchOnline(q) {
    if (onlineCache.has(q)) return onlineCache.get(q);
    const res = await fetch("/zhtag/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: q, mode: "tags", fallback: true, unknownMode: "fallback", normalize: true }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const data = await res.json();
    const english = String(data?.english ?? "").trim();
    onlineCache.set(q, english);
    return english;
}

/** 后端兜底翻译配好了没有（keep = 没配，不会真的翻译） */
function translatorReady() {
    const mode = String(TRANSLATOR?.fallback || "").toLowerCase();
    return mode === "llm" || mode === "google";
}

async function refreshTranslatorStatus() {
    try {
        const r = await fetch("/zhtag/status");
        if (!r.ok) return TRANSLATOR;
        const d = await r.json();
        TRANSLATOR = d?.translator || null;
    } catch (e) { /* 拿不到就当没配 */ }
    return TRANSLATOR;
}

/** 弹候选框（会异步补上「在线翻译」那一行） */
async function openCompletion(node, widget, el) {
    if (!S("complete")) return;
    ensurePopup();
    const frag = fragmentAt(el);
    if (!wantCompletion(frag.text)) { closePopup(); return; }
    const q = frag.text.trim();
    const limit = Math.max(3, Math.min(20, Number(S("completeLimit")) || 10));
    const seq = (STATE?.seq || 0) + 1;
    STATE = { el, widget, node, frag, rows: [], index: 0, seq, q };
    let results = [];
    try {
        results = await fetchCompletions(q, limit);
    } catch (e) {
        log("补全查询失败", e);
    }
    if (!STATE || STATE.seq !== seq) return;            // 用户又打字了，丢弃这次结果
    STATE.rows = results.map((r) => ({ ...r, kind: r.kind || (r.zh ? "zh" : "en") }));
    // 本地没有（或都不太准）时，联网翻译兜底
    const best = STATE.rows[0]?.score || 0;
    const willTryOnline = S("completeOnline") && q.length >= 2 && best < 80;
    if (!STATE.rows.length && !willTryOnline) {
        closePopup();                                   // 没候选也不联网 → 直接收摊，别留状态
        return;
    }
    if (STATE.rows.length) {
        renderPopup();
    } else if (POPUP) {
        POPUP.style.display = "none";
        POPUP.textContent = "";                         // 清掉上一轮的候选行，避免残留
    }
    if (!willTryOnline) return;
    if (!translatorReady()) {                           // 后端没配在线翻译 → 给一行提示，别静默失败
        if (TRANSLATOR === null) refreshTranslatorStatus();   // 后台刷新一次，配好后下次就准了
        STATE.rows = STATE.rows.concat([{ en: HINT_UNCONFIGURED, zh: "", score: 30, count: 0, kind: "hint" }]);
        renderPopup();
        return;
    }
    clearTimeout(widget._zht_online_timer);
    widget._zht_online_timer = setTimeout(async () => {
        let english = "";
        try {
            english = await fetchOnline(q);
        } catch (e) {
            log("在线翻译失败", e);
        }
        if (!english || !STATE || STATE.seq !== seq || STATE.q !== q) return;
        if (english.toLowerCase() === q.toLowerCase()) return;
        STATE.rows = STATE.rows.concat([{ en: english, zh: "", score: 30, count: 0, kind: "online" }]);
        renderPopup();
    }, ONLINE_DEBOUNCE);
}

function commitRow(i) {
    const st = STATE;
    if (!st) return;
    const row = st.rows[i];
    if (!row) return;
    if (row.kind === "hint") {                          // 提示行：不动文本框，只告诉用户怎么开
        toast("ZHTag 在线翻译", HINT_TEXT, true);
        refreshTranslatorStatus();
        closePopup();
        return;
    }
    const el = st.el;
    const value = String(el.value ?? "");
    const before = value.slice(0, st.frag.start);
    const after = value.slice(st.frag.end);
    let insert = String(row.en || "").trim();
    if (!insert) { closePopup(); return; }
    if (!after || !/^[\s,，、;；|\n\r]/.test(after)) insert += ", ";
    el.value = before + insert + after;
    const caret = (before + insert).length;
    try { el.selectionStart = el.selectionEnd = caret; } catch (e) { /* ignore */ }
    const prev = st.widget.value;
    st.widget.value = el.value;
    try { st.widget.callback?.(el.value); } catch (e) { /* ignore */ }
    try { st.node?.onWidgetChanged?.(st.widget.name, el.value, prev, st.widget); } catch (e) { /* ignore */ }
    try { app.graph?.setDirtyCanvas?.(true, true); } catch (e) { /* ignore */ }
    closePopup();
    try { el.focus(); } catch (e) { /* ignore */ }
}

/** 弹层打开时拦截按键；返回 true 表示这次按键已被吃掉 */
function handleCompletionKey(e, node, widget, el) {
    if (!POPUP || POPUP.style.display === "none" || !STATE) return false;
    if (e.isComposing || e.keyCode === 229) return false;
    const n = STATE.rows.length;
    if (e.key === "ArrowDown" && n) {
        STATE.index = (STATE.index + 1) % n;
        renderSelection();
    } else if (e.key === "ArrowUp" && n) {
        STATE.index = (STATE.index - 1 + n) % n;
        renderSelection();
    } else if ((e.key === "Enter" || e.key === "Tab") && n) {
        commitRow(STATE.index);
    } else if (e.key === "Escape") {
        closePopup();
    } else {
        return false;
    }
    e.preventDefault();
    e.stopPropagation();
    return true;
}

/* =====================================================================
 * 字段装饰：把补全与整句翻译挂到真实 textarea 上
 * ===================================================================== */

function isTextField(widget) {
    if (!widget) return false;
    if (typeof widget.value !== "string") return false;
    const type = (widget.type || "").toLowerCase();
    if (type === "text" || type === "string" || type === "customtext") return true;
    return !!(widget.options && (widget.options.multiline || widget.options.dynamicPrompts !== undefined));
}

async function translateWidget(node, widget, { silent = false } = {}) {
    if (widget._zht_busy) return;
    const value = String(widget.value ?? "");
    if (!value.trim() || !CJK.test(value)) return;
    if (value === widget._zht_last) return;            // 已经翻过且没变
    widget._zht_busy = true;
    try {
        const data = await translateText(value);
        const english = String(data?.english ?? "").trim();
        if (english && english !== value) {
            widget.value = english;
            widget._zht_last = english;
            try { widget.callback?.(english); } catch (e) { /* 有些版本 callback 只读 */ }
            try { node.onWidgetChanged?.(widget.name, english, value, widget); } catch (e) { /* ignore */ }
            try { app.graph?.setDirtyCanvas?.(true, true); } catch (e) { /* ignore */ }
            if (!silent) toast("中文Tag→英文", data?.info || "");
        } else if (!silent) {
            toast("ZHTag", "没有可翻译的内容");
        }
    } catch (e) {
        log("翻译失败", e);
        if (!silent) toast("ZHTag 翻译失败", String(e?.message || e));
    } finally {
        widget._zht_busy = false;
    }
}

function decorateTextField(node, widget) {
    if (!isTextField(widget) || widget._zht_hooked) return;
    widget._zht_hooked = true;

    // 1) 包装回调：拿不到 DOM 时也能在值变化时兜住
    const original = widget.callback;
    widget.callback = function (...args) {
        const ret = original?.apply(this, args);
        if (S("auto") && S("trigger") === "idle") {
            clearTimeout(widget._zht_timer);
            widget._zht_timer = setTimeout(() => translateWidget(node, widget, { silent: true }), Number(S("idleMs")) || 900);
        }
        return ret;
    };

    // 2) 绑定真实 textarea（新版 ComfyUI 会挂在 widget.inputEl 上）
    const bindEl = (el) => {
        if (!el || el._zht_el) return;
        el._zht_el = true;
        el.addEventListener("blur", () => {
            // 延后一点：点候选框时焦点会先离开（mousedown 已 preventDefault，这里只是兜底）
            setTimeout(closePopup, 120);
            if (S("auto") && S("trigger") === "blur") translateWidget(node, widget, { silent: true });
        });
        el.addEventListener("input", () => {
            if (S("auto") && S("trigger") === "idle") {
                clearTimeout(widget._zht_timer);
                widget._zht_timer = setTimeout(() => translateWidget(node, widget, { silent: true }), Number(S("idleMs")) || 900);
            }
            if (S("complete")) {
                clearTimeout(widget._zht_suggest_timer);
                widget._zht_suggest_timer = setTimeout(() => openCompletion(node, widget, el), SUGGEST_DEBOUNCE);
            }
        });
        // 中文输入法：拼字过程中先别弹，选词结束再弹
        el.addEventListener("compositionstart", () => closePopup());
        el.addEventListener("compositionend", () => {
            if (S("complete")) {
                clearTimeout(widget._zht_suggest_timer);
                widget._zht_suggest_timer = setTimeout(() => openCompletion(node, widget, el), SUGGEST_DEBOUNCE);
            }
        });
        el.addEventListener("keyup", (e) => {
            // 方向键/Home/End 移动光标后，按新位置重算片段
            if (!S("complete")) return;
            if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
                clearTimeout(widget._zht_suggest_timer);
                widget._zht_suggest_timer = setTimeout(() => openCompletion(node, widget, el), SUGGEST_DEBOUNCE);
            }
        });
        el.addEventListener("scroll", () => { if (STATE?.el === el) placePopup(); });
        el.addEventListener("keydown", (e) => {
            if (handleCompletionKey(e, node, widget, el)) return;      // 补全框打开时先吃按键
            if (e.ctrlKey && e.altKey && (e.key === "t" || e.key === "T")) {
                e.preventDefault();
                translateWidget(node, widget);
            } else if (e.ctrlKey && e.key === " ") {                    // Ctrl+Space 也能手动唤起
                if (S("complete")) {
                    e.preventDefault();
                    openCompletion(node, widget, el);
                }
            }
        });
    };
    bindEl(widget.inputEl || widget.element);
    if (!widget.inputEl && !widget.element) {
        // 老版本：文本框是延迟创建到 body 上的，等一小会儿再找
        setTimeout(() => {
            try {
                const el = document.querySelector(".comfy-multiline-input:focus, .comfy-multiline-input");
                bindEl(el);
            } catch (e) { /* ignore */ }
        }, 300);
    }
}

app.registerExtension({
    name: PLUGIN,

    settings: [
        setting(`${PLUGIN}.complete`, "ZHTag：IDE 式补全（打中文/拼音就出候选）", "boolean", DEFAULTS.complete),
        setting(`${PLUGIN}.completeLimit`, "ZHTag：补全候选数量", "number", DEFAULTS.completeLimit),
        setting(`${PLUGIN}.completeOnline`, "ZHTag：词库没有时在候选里给出「在线翻译」", "boolean", DEFAULTS.completeOnline),
        setting(`${PLUGIN}.auto`, "ZHTag：失焦/停顿时整句翻译", "boolean", DEFAULTS.auto),
        setting(`${PLUGIN}.trigger`, "ZHTag：整句翻译的触发时机", "combo", DEFAULTS.trigger,
            { options: ["blur", "idle", "off"] }),
        setting(`${PLUGIN}.idleMs`, "ZHTag：停顿多久后翻译（毫秒）", "number", DEFAULTS.idleMs),
        setting(`${PLUGIN}.unknownMode`, "ZHTag：词典没查到的词怎么办", "combo", DEFAULTS.unknownMode,
            { options: ["drop", "keep", "fallback"] }),
        setting(`${PLUGIN}.normalize`, "ZHTag：输出用 Danbooru 正名并按热度排序", "boolean", DEFAULTS.normalize),
        setting(`${PLUGIN}.fallback`, "ZHTag：整句翻译时走兜底翻译（LLM/在线）", "boolean", DEFAULTS.fallback),
        setting(`${PLUGIN}.showToast`, "ZHTag：翻译后弹出提示", "boolean", DEFAULTS.showToast),
    ],

    async setup() {
        log("已加载：IDE 式补全（中文/拼音→英文 tag）+ 失焦整句翻译 + 右键菜单 + Ctrl+Alt+T");
        ensurePopup();
        // 词库/兜底翻译状态自检（控制台可见；顺便判断「在线翻译」能不能用）
        try {
            const r = await fetch("/zhtag/status");
            if (r.ok) {
                const d = await r.json();
                TRANSLATOR = d?.translator || null;
                log(`词库 ${d.entries} 条，来源 ${(d.sources || []).join(", ")}`,
                    `；在线翻译：${translatorReady() ? d.translator.fallback : "未配置（config.json 里改 fallback）"}`);
            }
        } catch (e) {
            log("拿不到词库状态（后端接口未就绪？）", e);
        }
    },

    nodeCreated(node) {
        try {
            (node?.widgets || []).forEach((w) => decorateTextField(node, w));
        } catch (e) {
            log("nodeCreated 处理失败", e);
        }
    },

    async beforeRegisterNodeDef(nodeType) {
        const original = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function (canvas, options) {
            const ret = original?.apply(this, arguments);
            try {
                options.push({
                    content: "中文Tag→英文（本节点全部文本框）",
                    callback: async () => {
                        for (const w of (this.widgets || [])) {
                            if (isTextField(w) && CJK.test(String(w.value ?? ""))) {
                                await translateWidget(this, w, { silent: true });
                            }
                        }
                        toast("ZHTag", "本节点文本框已翻译");
                    },
                });
                options.push({
                    content: "ZHTag：查看词库状态",
                    callback: async () => {
                        try {
                            const r = await fetch("/zhtag/status");
                            const d = await r.json();
                            toast("ZHTag 词库", `${d.entries} 条中文词条；来源：${(d.sources || []).join("、") || "无"}`);
                        } catch (e) { toast("ZHTag", "读取失败：" + e); }
                    },
                });
                options.push({
                    content: "ZHTag：下载/更新社区词典",
                    callback: async () => {
                        toast("ZHTag", "开始下载社区词典，可能要等十几秒…", true);
                        try {
                            const r = await fetch("/zhtag/dict/download", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ ids: [], reload: true }),
                            });
                            const d = await r.json();
                            const lines = (d.results || []).map(
                                (x) => `${x.ok ? "✓" : "✗"} ${x.name || x.id}：${x.message || ""}`);
                            const head = d.entries ? `词库现有 ${d.entries} 条中文词条` : "下载结束";
                            toast("ZHTag 词典更新", [head, ...lines].join("\n"), true);
                            log("词典下载结果", d);
                        } catch (e) {
                            toast("ZHTag", "下载失败：" + e, true);
                            log("词典下载失败", e);
                        }
                    },
                });
            } catch (e) {
                log("菜单注入失败", e);
            }
            return ret;
        };
    },
});

// 全局快捷键：选中节点后 Ctrl+Alt+T
try {
    window.addEventListener("keydown", (e) => {
        if (!(e.ctrlKey && e.altKey && (e.key === "t" || e.key === "T"))) return;
        const nodes = app.canvas?.selected_nodes ? Object.values(app.canvas.selected_nodes) : [];
        if (!nodes.length) return;
        e.preventDefault();
        (async () => {
            for (const node of nodes) {
                for (const w of (node.widgets || [])) {
                    if (isTextField(w) && CJK.test(String(w.value ?? ""))) await translateWidget(node, w, { silent: true });
                }
            }
            toast("ZHTag", `已翻译 ${nodes.length} 个节点`);
        })();
    });
} catch (e) {
    log("快捷键注册失败", e);
}

// 全局快捷键：窗口缩放或滚动画布时，候选框位置会失效，直接关掉
try {
    window.addEventListener("resize", () => closePopup());
    window.addEventListener("wheel", (e) => {
        try {
            if (POPUP && e?.target && POPUP.contains?.(e.target)) return;   // 在候选框里滚不算
        } catch (err) { /* ignore */ }
        closePopup();
    }, { passive: true });
} catch (e) {
    log("窗口事件注册失败", e);
}

// 暴露给测试与高级用户
window.ZHTag = {
    translateText,
    fragmentAt,
    wantCompletion,
    openCompletion,
    commitRow,
    closePopup,
    handleCompletionKey,
    refreshTranslatorStatus,
    translatorReady,
    getPopupState: () => STATE,
    getPopupEl: () => POPUP,
};
