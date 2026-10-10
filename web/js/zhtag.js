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
    showToast: true,
    complete: true, // IDE 式补全开关
    completeLimit: 15,
    onlineProvider: "google", // off（只用词典）| google | microsoft | baidu | youdao | llm
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
            fallback: onlineOn(),               // 单一的开关：翻译方式不是「词典」才联网
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
// 在线翻译状态（后端为准）：{mode, providers:[{id,desc}], status:{google:{ok,at,msg}, microsoft:{...}}}
let ONLINE = { mode: null, providers: [{ id: "google", desc: "谷歌在线翻译" }, { id: "microsoft", desc: "微软在线翻译" }], status: {} };

const PROVIDER_LABEL = { off: "词典", google: "谷歌", microsoft: "微软", baidu: "百度", youdao: "有道", llm: "LLM" };
// 候选来源标签（后端 kind → 界面文字）
const KIND_LABEL = { zh: "", pinyin: "拼音", en: "英文标签", enword: "英文联想", phrase: "词组" };
const NEEDS_KEYS = { baidu: "baidu_appid / baidu_key", youdao: "youdao_appid / youdao_key" };
const HINT_UNCONFIGURED = "在线翻译没开 —— 点右上角「谷歌 / 微软 / 百度 / 有道」开启";

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
.zht-pop .zht-head{padding:2px 10px 3px;font-size:11px;opacity:.62;border-bottom:1px solid #33333c;
  display:flex;justify-content:space-between;align-items:center;gap:10px}
.zht-pop .zht-sw{display:flex;align-items:center;gap:4px;opacity:1}
.zht-pop .zht-sw-label{opacity:.75}
.zht-pop .zht-pill{padding:0 6px;border:1px solid #4a4a56;border-radius:9px;cursor:pointer;
  font-weight:600;font-size:11px;line-height:15px;background:#26262e;color:#c9c9d4}
.zht-pop .zht-pill:hover{border-color:#6f9fe0;color:#fff}
.zht-pop .zht-pill.on{background:#2f6fd0;border-color:#2f6fd0;color:#fff}
.zht-pop .zht-online{color:#8fd3ff}
.zht-pop .zht-phrase{color:#c9f0a4}
.zht-pop .zht-dim{opacity:.6}
.zht-pop .zht-warn{color:#ffd479}
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

/**
 * 点/摸到别的地方就关掉候选框。
 *
 * 为什么要单独装这个：画布、节点标题这些地方点了不一定能给 textarea 触发 blur，
 * 于是候选框会一直挂在那儿。这里在 document 上抓 pointerdown（捕获阶段）：
 * 只要不是点在候选框里、也不是点在当前那个文本框里，就直接关。
 */
let OUTSIDE_HOOKED = false;
function installOutsideCloser() {
    if (OUTSIDE_HOOKED || typeof document === "undefined") return;
    OUTSIDE_HOOKED = true;
    const handler = (e) => {
        if (!STATE) return;
        try {
            const t = e?.target;
            if (POPUP && t && (t === POPUP || POPUP.contains?.(t))) return;   // 点候选框本身：不关
            if (STATE.el && (t === STATE.el || STATE.el.contains?.(t))) return;  // 点当前文本框：不关
        } catch (err) { /* 保守起见还是关掉 */ }
        closePopup();
    };
    try { document.addEventListener("pointerdown", handler, true); } catch (e) { /* ignore */ }
    try { document.addEventListener("mousedown", handler, true); } catch (e) { /* 老环境只有 mouse 事件 */ }
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
    const tips = document.createElement("span");
    tips.textContent = "↑↓ 选择 · Enter 采用 · Esc 关闭";
    head.appendChild(tips);
    head.appendChild(buildSwitch());
    POPUP.appendChild(head);
    rows.forEach((r, i) => {
        const row = document.createElement("div");
        row.className = "zht-row" + (i === STATE.index ? " on" : "")
            + (r.kind === "online" ? " zht-online" : "")
            + (r.kind === "phrase" ? " zht-phrase" : "")
            + (r.kind === "loading" ? " zht-dim" : "")
            + (r.kind === "hint" || r.kind === "error" ? " zht-warn" : "");
        row.dataset.i = String(i);
        const en = document.createElement("span");
        en.className = "zht-en";
        en.textContent = r.kind === "online" ? `在线翻译 → ${r.en}` : r.en;
        const src = document.createElement("span");
        src.className = "zht-src";
        // 优先显示中文（英文候选也会尽量配上中文注释），没有中文才退化成来源标签
        const kindLabel = KIND_LABEL[r.kind] || "";
        const kindTag = r.kind === "phrase" ? " · 词组" : (r.kind === "pinyin" ? " · 拼音" : "");
        src.textContent = r.zh ? `${r.zh}${kindTag}` : kindLabel;
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

/** 右上角的「词典 / 谷歌 / 微软 / 百度 / 有道」切换按钮（带连通状态灯） */
function buildSwitch() {
    const wrap = document.createElement("span");
    wrap.className = "zht-sw";
    const label = document.createElement("span");
    label.className = "zht-sw-label";
    label.textContent = "翻译：";
    wrap.appendChild(label);
    const items = [{ id: "off", desc: "只用词典，不联网" }]
        .concat(ONLINE.providers || [
            { id: "google", desc: "谷歌在线翻译" }, { id: "microsoft", desc: "微软在线翻译" },
            { id: "baidu", desc: "百度在线翻译" }, { id: "youdao", desc: "有道在线翻译" }]);
    items.forEach((p) => {
        const b = document.createElement("b");
        b.className = "zht-pill" + (ONLINE.mode === p.id ? " on" : "");
        b.dataset.mode = p.id;
        const st = ONLINE.status?.[p.id];
        const need = NEEDS_KEYS[p.id];
        const dot = need && p.configured === false ? "·" : (st ? (st.ok ? "●" : "✗") : "");
        b.textContent = `${PROVIDER_LABEL[p.id] || p.id}${dot}`;
        b.title = need && p.configured === false
            ? `${p.desc}：还没填 ${need}（在 data/user/config.json 里填）`
            : (st ? (st.ok ? `${p.desc}：上次正常` : `${p.desc}：上次失败 ${st.msg || ""}`) : `${p.desc}（点一下切过去）`);
        b.addEventListener("mousedown", (e) => {
            e.preventDefault();
            e.stopPropagation();
            setOnlineMode(p.id);
        });
        wrap.appendChild(b);
    });
    return wrap;
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

/** 在线翻译开着吗（只有「词典」是关） */
function onlineOn() {
    return ONLINE.mode !== "off" && ONLINE.mode !== null;
}

/** 当前服务商能不能用（百度/有道要先填 appid+key） */
function providerReady(mode = ONLINE.mode) {
    if (mode === "off") return false;
    if (mode === "llm") return true;
    const p = (ONLINE.providers || []).find((x) => x.id === mode);
    return p ? p.configured !== false : true;
}

async function refreshOnlineStatus({ test = "" } = {}) {
    try {
        const url = "/zhtag/online" + (test ? `?test=${encodeURIComponent(test)}` : "");
        const r = await fetch(url);
        if (!r.ok) return ONLINE;
        const d = await r.json();
        if (d?.mode) {
            ONLINE = {
                mode: d.mode,
                providers: d.providers || ONLINE.providers,
                off: d.off || ONLINE.off,
                status: d.status || {},
            };
        }
    } catch (e) { /* 拿不到就保持原样 */ }
    return ONLINE;
}

/** 点「词典 / 谷歌 / 微软 / 百度 / 有道」：先立刻切过去（不等网络），连通性检查放后台 */
async function setOnlineMode(mode, { quiet = false } = {}) {
    const label = PROVIDER_LABEL[mode] || mode;
    ONLINE.mode = mode;                                     // 乐观更新：按钮立刻高亮
    refreshPopupIfOpen();
    try { app.ui?.settings?.setSettingValue?.(`${PLUGIN}.onlineProvider`, mode); } catch (e) { /* ignore */ }
    if (!quiet) toast("ZHTag", mode === "off" ? "翻译方式 → 只用词典（不联网）" : `翻译方式 → ${label}（正在后台测连通…）`, true);
    // 1) 立刻把配置写回后端（不测连通，几十毫秒就回）
    try {
        const r = await fetch("/zhtag/online", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode }),
        });
        const d = await r.json();
        if (d?.mode) ONLINE = { mode: d.mode, providers: d.providers || ONLINE.providers, off: d.off || ONLINE.off, status: d.status || ONLINE.status };
    } catch (e) {
        toast("ZHTag", "切换失败：" + e, true);
        return ONLINE.mode;
    }
    // 当前片段重新查一次（把上一轮的在线结果丢掉）
    if (STATE?.el && STATE?.widget && STATE?.node) {
        onlineCache.clear();
        STATE.rows = STATE.rows.filter((r) => !["online", "hint", "error", "loading"].includes(r.kind));
        openCompletion(STATE.node, STATE.widget, STATE.el);
    }
    if (mode === "off") return ONLINE.mode;
    // 2) 后台测一次连通（真发一条翻译），好了再更新状态灯 + 提示
    if (mode !== "off" && mode !== "llm") {
        const seq = ONLINE.mode;
        try {
            const r = await fetch(`/zhtag/online?test=${encodeURIComponent(mode)}`);
            const d = await r.json();
            if (d?.status && ONLINE.mode === seq) {
                ONLINE = { ...ONLINE, status: d.status, providers: d.providers || ONLINE.providers };
                refreshPopupIfOpen();
                if (!quiet) {
                    const st = d.status?.[mode];
                    const need = NEEDS_KEYS[mode];
                    toast("ZHTag", st?.ok
                        ? `翻译方式：${label} · 连通正常`
                        : (need ? `${label}还没配置 —— 在 data/user/config.json 里填 ${need}` :
                           `${label} · 连不上（${st?.msg || "无返回"}），可以换一个`), true);
                }
            }
        } catch (e) { /* 测不通就算了，用的时候自然会失败 */ }
    }
    return ONLINE.mode;
}

/** 候选框开着就重画一下（切换按钮和在线翻译行需要立刻反映新状态） */
function refreshPopupIfOpen() {
    if (POPUP && STATE && POPUP.style.display !== "none") renderPopup();
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
    // 本地没有（或都不太准）时，联网翻译兜底（翻译方式=词典 时完全不联网）
    const best = STATE.rows[0]?.score || 0;
    const willTryOnline = onlineOn() && q.length >= 2 && best < 80;
    if (!STATE.rows.length && !willTryOnline) {
        closePopup();                                   // 没候选也不联网 → 直接收摊，别留状态
        return;
    }
    if (!STATE.rows.length) {
        // 只有在线翻译这一条路：先把框显示出来（右上角的切换按钮要能点）
        STATE.rows = [{ en: `正在用${PROVIDER_LABEL[ONLINE.mode] || "在线"}翻译…`, zh: "",
                        score: 30, count: 0, kind: "loading" }];
    }
    renderPopup();
    if (!willTryOnline) return;
    if (!providerReady()) {                             // 没开/没配好 → 给一行提示（点右上角就能改）
        refreshOnlineStatus();
        const need = NEEDS_KEYS[ONLINE.mode];
        STATE.rows = STATE.rows.filter((r) => r.kind !== "loading")
            .concat([{ en: need ? `${PROVIDER_LABEL[ONLINE.mode]}翻译还没配置 —— 点这里看怎么填` : HINT_UNCONFIGURED,
                      zh: "", score: 30, count: 0, kind: "hint" }]);
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
        if (!STATE || STATE.seq !== seq || STATE.q !== q) return;
        const drop = (kind) => STATE.rows.filter((r) => r.kind !== kind);
        const usable = english && english.toLowerCase() !== q.toLowerCase();
        if (usable) {
            STATE.rows = drop("loading").concat([{ en: english, zh: "", score: 30, count: 0, kind: "online" }]);
        } else {
            const label = PROVIDER_LABEL[ONLINE.mode] || "在线";
            const st = ONLINE.status?.[ONLINE.mode];
            STATE.rows = drop("loading").concat([{
                en: `${label}翻译${english ? "没得到结果" : "连不上"}${st?.msg ? "（" + String(st.msg).slice(0, 40) + "）" : ""}`
                    + " —— 可点右上角换一个",
                zh: "", score: 20, count: 0, kind: "error",
            }]);
            refreshOnlineStatus();                      // 把状态灯刷新一下
        }
        renderPopup();
    }, ONLINE_DEBOUNCE);
}

function commitRow(i) {
    const st = STATE;
    if (!st) return;
    const row = st.rows[i];
    if (!row) return;
    if (row.kind === "loading") return;                 // 还在翻译，别把占位文字写进文本框
    if (row.kind === "error") {                         // 失败提示：只提示，不动文本框
        toast("ZHTag 在线翻译", row.en, true);
        return;
    }
    if (row.kind === "hint") {                          // 没开/没配好在线翻译：只提示，不动文本框
        const need = NEEDS_KEYS[ONLINE.mode];
        toast("ZHTag", need
            ? `在 custom_nodes/comfyui-zh-tag/data/user/config.json 里填 ${need}，或点弹层右上角换成别的（词典=不联网）`
            : "现在只用词典（不联网）。想联网翻译就点弹层右上角的「谷歌 / 微软 / 百度 / 有道」", true);
        refreshOnlineStatus();
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
    // 文本框元素在 1.5x 前端里可能晚一步才建好（widget.element 一开始是 undefined），
    // 所以这里定时重试几次；绝不退化成「随便找一个 textarea 绑上去」——那会绑错节点。
    const resolveEl = () => {
        const w = widget;
        return w.inputEl || w.element
            || w.elementWrapper?.querySelector?.("textarea")
            || null;
    };
    const tryBind = (attempt = 0) => {
        const el = resolveEl();
        if (el) { bindEl(el); return; }
        if (attempt < 12) {
            setTimeout(() => tryBind(attempt + 1), 250);
        } else {
            log(`「${widget.name}」的文本框一直没出现，跳过绑定（不影响打字，只是没有补全）`);
        }
    };
    tryBind();
}

/** 把一个节点上所有文本小部件都装饰一遍（补丁式：新出现的小部件也能补上） */
function decorateNode(node) {
    if (!node || node._zht_decorated === undefined) node._zht_decorated = 0;
    const widgets = node.widgets || [];
    if (widgets.length === node._zht_decorated && node._zht_decorated > 0) return;
    widgets.forEach((w) => decorateTextField(node, w));
    node._zht_decorated = widgets.length;
}

app.registerExtension({
    name: PLUGIN,

    settings: [
        setting(`${PLUGIN}.complete`, "ZHTag：IDE 式补全（打中文/拼音就出候选）", "boolean", DEFAULTS.complete),
        setting(`${PLUGIN}.completeLimit`, "ZHTag：补全候选数量", "number", DEFAULTS.completeLimit),
        setting(`${PLUGIN}.onlineProvider`, "ZHTag：翻译方式（词典 / 谷歌 / 微软 / 百度 / 有道）", "combo", DEFAULTS.onlineProvider,
            {
                options: ["off", "google", "microsoft", "baidu", "youdao", "llm"],
                onChange: (v) => {
                    if (v !== ONLINE.mode) setOnlineMode(String(v || "off"), { quiet: true });
                },
            }),
        setting(`${PLUGIN}.auto`, "ZHTag：失焦/停顿时整句翻译", "boolean", DEFAULTS.auto),
        setting(`${PLUGIN}.trigger`, "ZHTag：整句翻译的触发时机", "combo", DEFAULTS.trigger,
            { options: ["blur", "idle", "off"] }),
        setting(`${PLUGIN}.idleMs`, "ZHTag：停顿多久后翻译（毫秒）", "number", DEFAULTS.idleMs),
        setting(`${PLUGIN}.unknownMode`, "ZHTag：整句翻译时词典没查到的词怎么办", "combo", DEFAULTS.unknownMode,
            { options: ["drop", "keep", "fallback"] }),
        setting(`${PLUGIN}.normalize`, "ZHTag：输出用 Danbooru 正名并按热度排序", "boolean", DEFAULTS.normalize),
        setting(`${PLUGIN}.showToast`, "ZHTag：翻译后弹出提示", "boolean", DEFAULTS.showToast),
    ],

    async setup() {
        log("已加载：IDE 式补全（中文/拼音→英文 tag）+ 失焦整句翻译 + 右键菜单 + Ctrl+Alt+T");
        ensurePopup();
        installOutsideCloser();
        // 词库 + 在线翻译状态自检（控制台可见；右上角按钮的状态灯也用它）
        try {
            const r = await fetch("/zhtag/status");
            if (r.ok) {
                const d = await r.json();
                log(`词库 ${d.entries} 条，来源 ${(d.sources || []).join(", ")}`);
            }
        } catch (e) {
            log("拿不到词库状态（后端接口未就绪？）", e);
        }
        await refreshOnlineStatus();
        try { app.ui?.settings?.setSettingValue?.(`${PLUGIN}.onlineProvider`, ONLINE.mode); } catch (e) { /* ignore */ }
        log(`在线翻译：${PROVIDER_LABEL[ONLINE.mode] || ONLINE.mode}（弹层右上角可切换）`);
    },

    nodeCreated(node) {
        try {
            decorateNode(node);
        } catch (e) {
            log("nodeCreated 处理失败", e);
        }
    },

    async beforeRegisterNodeDef(nodeType) {
        // 小部件可能是节点建好之后才加上去的（比如子图节点上的「提升小部件」），
        // 所以顺手在画节点时补一遍装饰。
        const originalDraw = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function (ctx) {
            try { decorateNode(this); } catch (e) { /* ignore */ }
            return originalDraw?.apply(this, arguments);
        };

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
    refreshOnlineStatus,
    setOnlineMode,
    onlineOn,
    providerReady,
    installOutsideCloser,
    getOnline: () => ONLINE,
    getPopupState: () => STATE,
    getPopupEl: () => POPUP,
};
