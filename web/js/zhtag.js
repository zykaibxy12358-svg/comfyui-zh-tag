/**
 * ZHTag 前端扩展：在文本框里输入中文 → 自动/手动翻成英文 tag。
 *
 * · 自动翻译：默认「失焦时」触发（打字时不会打断你），可选「停顿后」
 * · 手动翻译：节点右键菜单「中文Tag→英文」，或全选节点后按 Ctrl+Alt+T
 * · 所有文本输入框通用（CLIPTextEncode 与 ZHTag 节点都在内）
 *
 * 只用到公开 API（app.registerExtension / nodeCreated / getExtraMenuOptions / settings），
 * 并对缺 API 的老版本做了降级保护。
 */
import { app } from "../../../scripts/app.js";

const PLUGIN = "ZHTag";
const CJK = /[\u3400-\u9fff\uf900-\ufaff]/;
const log = (...a) => console.log(`[${PLUGIN}]`, ...a);

const DEFAULTS = {
    auto: true,
    trigger: "blur", // blur | idle | off
    idleMs: 900,
    fallback: false, // 是否让后端走兜底翻译（LLM/在线）
    showToast: true,
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

function toast(summary, detail) {
    if (!S("showToast")) return;
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
        body: JSON.stringify({ text, mode: "tags", fallback: !!S("fallback") }),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return await res.json();
}

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
            if (S("auto") && S("trigger") === "blur") translateWidget(node, widget, { silent: true });
        });
        el.addEventListener("input", () => {
            if (!S("auto") || S("trigger") !== "idle") return;
            clearTimeout(widget._zht_timer);
            widget._zht_timer = setTimeout(() => translateWidget(node, widget, { silent: true }), Number(S("idleMs")) || 900);
        });
        el.addEventListener("keydown", (e) => {
            if (e.ctrlKey && e.altKey && (e.key === "t" || e.key === "T")) {
                e.preventDefault();
                translateWidget(node, widget);
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
        setting(`${PLUGIN}.auto`, "ZHTag：自动把中文翻成英文Tag", "boolean", DEFAULTS.auto),
        setting(`${PLUGIN}.trigger`, "ZHTag：自动触发时机", "combo", DEFAULTS.trigger,
            { options: ["blur", "idle", "off"] }),
        setting(`${PLUGIN}.idleMs`, "ZHTag：停顿多久后翻译（毫秒）", "number", DEFAULTS.idleMs),
        setting(`${PLUGIN}.fallback`, "ZHTag：词库没有时走兜底翻译（LLM/在线）", "boolean", DEFAULTS.fallback),
        setting(`${PLUGIN}.showToast`, "ZHTag：翻译后弹出提示", "boolean", DEFAULTS.showToast),
    ],

    async setup() {
        log("已加载：文本框失焦/停顿自动翻译 + 右键菜单 + Ctrl+Alt+T");
        // 词库状态自检（控制台可见）
        try {
            const r = await fetch("/zhtag/status");
            if (r.ok) {
                const d = await r.json();
                log(`词库 ${d.entries} 条，来源 ${(d.sources || []).join(", ")}`);
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

window.ZHTag = { translateText };
