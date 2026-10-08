/**
 * 真机端到端验证：用 Chrome DevTools Protocol 在真实浏览器里跑一遍补全。
 *
 *   node tests/e2e_complete.mjs            # 需要 ComfyUI 在 8188、Chrome 开着 9222 调试端口
 *
 * 做的是：造一个真 textarea（真 DOM/真 getComputedStyle/真 fetch）→ 调 openCompletion
 * → 检查候选框渲染 → 模拟 ↓ 和 Enter → 检查文本框被替换成英文 tag。
 */
const PORT = process.env.CDP_PORT || 9222;

async function main() {
    const targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
    const page = targets.find((t) => t.type === 'page' && /8188/.test(t.url || ''));
    if (!page) {
        console.error('找不到 ComfyUI 页面（Chrome 调试端口上没有 8188 的标签页）');
        process.exit(1);
    }
    const ws = new WebSocket(page.webSocketDebuggerUrl);
    let id = 0;
    const pending = new Map();
    ws.addEventListener('message', (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.id && pending.has(msg.id)) {
            pending.get(msg.id)(msg);
            pending.delete(msg.id);
        }
    });
    await new Promise((res, rej) => {
        ws.addEventListener('open', res);
        ws.addEventListener('error', rej);
    });

    const evaluate = (expression) => new Promise((resolve, reject) => {
        const myId = ++id;
        pending.set(myId, (msg) => {
            if (msg.error) return reject(new Error(JSON.stringify(msg.error)));
            const r = msg.result?.result;
            if (msg.result?.exceptionDetails) {
                return reject(new Error(JSON.stringify(msg.result.exceptionDetails.exception?.description
                    || msg.result.exceptionDetails.text)));
            }
            resolve(r?.value);
        });
        ws.send(JSON.stringify({
            id: myId, method: 'Runtime.evaluate',
            params: { expression, awaitPromise: true, returnByValue: true },
        }));
    });

    const script = `(async () => {
        const Z = window.ZHTag;
        if (!Z) return { error: 'window.ZHTag 不存在（扩展没加载？）' };
        const ta = document.createElement('textarea');
        ta.style.cssText = 'position:fixed;left:40px;top:40px;width:300px;height:80px;font:13px monospace;';
        document.body.appendChild(ta);
        ta.value = 'skirt, lanfa';
        ta.selectionStart = ta.selectionEnd = 12;
        const widget = { name: 'text', type: 'customtext', value: ta.value,
                         options: { multiline: true }, inputEl: ta, callback() {} };
        const node = { widgets: [widget], onWidgetChanged() {} };
        await Z.openCompletion(node, widget, ta);
        await new Promise((r) => setTimeout(r, 500));
        const pop = document.querySelector('.zht-pop');
        const rows = pop ? [...pop.querySelectorAll('.zht-row')].map((x) => x.textContent) : [];
        const box = { display: pop?.style.display, left: pop?.style.left, top: pop?.style.top };
        const before = ta.value;
        const key = (k) => Z.handleCompletionKey({ key: k, isComposing: false,
            preventDefault() {}, stopPropagation() {} }, node, widget, ta);
        const eatenDown = key('ArrowDown');
        key('Enter');
        const afterEnter = ta.value;
        // 第二个场景：中文 + 词库里没有的词（在线翻译行）
        ta.value = '蓝发';
        ta.selectionStart = ta.selectionEnd = 2;
        await Z.openCompletion(node, widget, ta);
        await new Promise((r) => setTimeout(r, 400));
        const zhRows = pop ? [...pop.querySelectorAll('.zht-row')].map((x) => x.textContent) : [];
        ta.value = 'qianziwoya';
        ta.selectionStart = ta.selectionEnd = 10;
        await Z.openCompletion(node, widget, ta);
        await new Promise((r) => setTimeout(r, 2500));
        const onlineRows = pop ? [...pop.querySelectorAll('.zht-row')].map((x) => x.textContent) : [];
        Z.closePopup();
        ta.remove();
        return { box, rows, before, eatenDown, afterEnter, widgetValue: widget.value, zhRows, onlineRows,
                 closed: document.querySelector('.zht-pop')?.style.display };
    })()`;

    const out = await evaluate(script);
    console.log(JSON.stringify(out, null, 2));

    const checks = [
        [out?.box?.display === 'block', '候选框真的显示了'],
        [Array.isArray(out?.rows) && out.rows.length > 0, '候选行渲染出来了'],
        [/blue hair/.test(out?.rows?.[0] || ''), `第一行是 blue hair：${out?.rows?.[0]}`],
        [out?.eatenDown === true, '↓ 被补全框处理'],
        [out?.afterEnter === 'skirt, blue hair, ', `Enter 替换成英文 tag：${JSON.stringify(out?.afterEnter)}`],
        [out?.widgetValue === 'skirt, blue hair, ', '节点值同步'],
        [Array.isArray(out?.zhRows) && /blue hair/.test(out.zhRows[0] || ''), `中文「蓝发」有候选：${out?.zhRows?.[0]}`],
        [Array.isArray(out?.onlineRows) && out.onlineRows.some((r) => /在线翻译/.test(r)),
            `查不到的词给出在线翻译行：${JSON.stringify(out?.onlineRows)}`],
        [out?.closed === 'none', '关闭后弹层隐藏'],
    ];
    let fail = 0;
    for (const [okv, label] of checks) {
        console.log(`${okv ? '  ✓' : '  ✗'} ${label}`);
        if (!okv) fail++;
    }
    ws.close();
    console.log(`\n结果：${checks.length - fail} 通过 / ${fail} 失败`);
    process.exit(fail ? 1 : 0);
}

main().catch((e) => { console.error('E2E 失败：', e); process.exit(1); });
