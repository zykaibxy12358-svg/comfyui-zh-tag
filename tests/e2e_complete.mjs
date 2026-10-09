/**
 * 真机端到端验证：用 Chrome DevTools Protocol 在真实浏览器里跑一遍补全。
 *
 *   node tests/e2e_complete.mjs            # 需要 ComfyUI 在 8188、Chrome 开着 9222 调试端口
 *   COMFY_PORT=8189 node tests/e2e_complete.mjs   # 换端口（验证时不影响你自己在用的实例）
 *
 * 做的是：造一个真 textarea（真 DOM/真 getComputedStyle/真 fetch）→ 调 openCompletion
 * → 检查候选框渲染 → 模拟 ↓ 和 Enter → 检查文本框被替换成英文 tag。
 */
const PORT = process.env.CDP_PORT || 9222;
const COMFY_PORT = process.env.COMFY_PORT || 8188;

async function main() {
    const targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
    const page = targets.find((t) => t.type === 'page' && new RegExp(`:${COMFY_PORT}/`).test(t.url || ''));
    if (!page) {
        console.error(`找不到 ComfyUI 页面（调试端口 ${PORT} 上没有 ${COMFY_PORT} 的标签页）`);
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
        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
        await Z.refreshOnlineStatus();
        const ta = document.createElement('textarea');
        ta.style.cssText = 'position:fixed;left:40px;top:40px;width:300px;height:80px;font:13px monospace;';
        document.body.appendChild(ta);
        ta.value = 'skirt, lanfa';
        ta.selectionStart = ta.selectionEnd = 12;
        const widget = { name: 'text', type: 'customtext', value: ta.value,
                         options: { multiline: true }, inputEl: ta, callback() {} };
        const node = { widgets: [widget], onWidgetChanged() {} };
        await Z.openCompletion(node, widget, ta);
        await sleep(500);
        const pop = document.querySelector('.zht-pop');
        const rows = pop ? [...pop.querySelectorAll('.zht-row')].map((x) => x.textContent) : [];
        const box = { display: pop?.style.display, left: pop?.style.left, top: pop?.style.top };
        const before = ta.value;
        const key = (k) => Z.handleCompletionKey({ key: k, isComposing: false,
            preventDefault() {}, stopPropagation() {} }, node, widget, ta);
        const eatenDown = key('ArrowDown');
        key('Enter');
        const afterEnter = ta.value;

        // 场景二：中文
        ta.value = '蓝发';
        ta.selectionStart = ta.selectionEnd = 2;
        await Z.openCompletion(node, widget, ta);
        await sleep(400);
        const zhRows = pop ? [...pop.querySelectorAll('.zht-row')].map((x) => x.textContent) : [];

        // 场景三：词库里没有的中文 → 谷歌在线翻译
        ta.value = '霓虹灯牌';
        ta.selectionStart = ta.selectionEnd = 4;
        const modeBefore = Z.getOnline().mode;
        await Z.openCompletion(node, widget, ta);
        await sleep(3000);
        const onlineRows = pop ? [...pop.querySelectorAll('.zht-row')].map((x) => x.textContent) : [];
        Z.commitRow(0);
        const afterOnlineEnter = ta.value;

        // 场景四：右上角切换按钮（点击立刻生效，测连通在后台）
        ta.value = '霓虹灯牌';
        ta.selectionStart = ta.selectionEnd = 4;
        await Z.openCompletion(node, widget, ta);
        await sleep(200);
        const pills = [...pop.querySelectorAll('.zht-pill')].map((x) => x.textContent);
        const ms = [...pop.querySelectorAll('.zht-pill')].find((x) => /微软/.test(x.textContent));
        ms.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        await sleep(120);
        const modeAfterMs = Z.getOnline().mode;
        const msOnNow = [...pop.querySelectorAll('.zht-pill')]
            .map((x) => x.textContent + (x.classList.contains('on') ? '←当前' : ''));
        // 等后台连通性测试（微软连不上，超时上限 8 秒）
        for (let i = 0; i < 60 && !Z.getOnline().status?.microsoft; i++) await sleep(500);
        const pillsAfter = [...pop.querySelectorAll('.zht-pill')].map((x) => x.textContent);
        const gl = [...pop.querySelectorAll('.zht-pill')].find((x) => /谷歌/.test(x.textContent));
        gl.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        await sleep(300);
        const modeBack = Z.getOnline().mode;
        // 场景五：全词联想（英文）与词组（中文）
        await sleep(1500);                 // 等切换触发的重新查询落地，别读到上一轮的候选
        ta.value = 'breasts';
        ta.selectionStart = ta.selectionEnd = 7;
        await Z.openCompletion(node, widget, ta);
        await sleep(500);
        const wordRows = pop ? [...pop.querySelectorAll('.zht-row')].map((x) => x.textContent) : [];
        ta.value = '巨大乳房';
        ta.selectionStart = ta.selectionEnd = 4;
        await Z.openCompletion(node, widget, ta);
        await sleep(500);
        const phraseRows = pop ? [...pop.querySelectorAll('.zht-row')].map((x) => x.textContent) : [];
        Z.commitRow(0);
        const afterPhrase = ta.value;
        ta.value = '黑色蕾丝';
        ta.selectionStart = ta.selectionEnd = 4;
        await Z.openCompletion(node, widget, ta);
        await sleep(500);
        const laceRows = pop ? [...pop.querySelectorAll('.zht-row')].map((x) => x.textContent) : [];
        Z.closePopup();
        ta.remove();
        return { box, rows, before, eatenDown, afterEnter, zhRows, onlineRows,
                 afterOnlineEnter, modeBefore, pills, modeAfterMs, msOnNow, pillsAfter, modeBack,
                 wordRows, phraseRows, afterPhrase, laceRows,
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
        [Array.isArray(out?.zhRows) && /blue hair/.test(out.zhRows[0] || ''), `中文「蓝发」有候选：${out?.zhRows?.[0]}`],
        [out?.modeBefore === 'google', `在线翻译默认是谷歌：${out?.modeBefore}`],
        [Array.isArray(out?.onlineRows) && out.onlineRows.some((r) => /在线翻译/.test(r)),
            `词库没有的词走在线翻译：${JSON.stringify(out?.onlineRows)}`],
        [/neon|lights|sign|lamp/i.test((out?.onlineRows || []).join(' ')),
            `谷歌真的翻出来了：${JSON.stringify(out?.onlineRows)}`],
        [!!(out?.afterOnlineEnter || '').trim() && /^[a-z0-9_ ,()]+$/.test(out.afterOnlineEnter),
            `采用在线翻译结果：${JSON.stringify(out?.afterOnlineEnter)}`],
        [Array.isArray(out?.pills) && out.pills.length === 5 && /词典/.test(out.pills[0]),
            `弹出层有 5 个按钮（词典/谷歌/微软/百度/有道）：${JSON.stringify(out?.pills)}`],
        [Array.isArray(out?.pills) && out.pills.some((p) => /百度/.test(p) && /·/.test(p)),
            `没填 key 的百度显示「·」：${JSON.stringify(out?.pills)}`],
        [out?.modeAfterMs === 'microsoft', `点「微软」立刻切过去（不等测连通）：${out?.modeAfterMs}`],
        [Array.isArray(out?.msOnNow) && out.msOnNow.some((p) => /微软/.test(p) && /←当前/.test(p)),
            `切换后微软按钮立刻高亮：${JSON.stringify(out?.msOnNow)}`],
        [Array.isArray(out?.pillsAfter) && out.pillsAfter.some((p) => /微软/.test(p) && /✗/.test(p)),
            `微软连不上时后台把状态灯点亮成 ✗：${JSON.stringify(out?.pillsAfter)}`],
        [out?.modeBack === 'google', `点回「谷歌」：${out?.modeBack}`],
        [Array.isArray(out?.wordRows) && out.wordRows.some((r) => /huge breasts/.test(r)),
            `breasts → 联想到 huge breasts：${JSON.stringify(out?.wordRows)}`],
        [Array.isArray(out?.phraseRows) && /huge breasts/.test(out.phraseRows[0] || '')
            && /词组/.test(out.phraseRows[0] || ''),
            `巨大乳房 → 词组 huge breasts：${out?.phraseRows?.[0]}`],
        [out?.afterPhrase === 'huge breasts, ', `采用词组：${JSON.stringify(out?.afterPhrase)}`],
        [Array.isArray(out?.laceRows) && /black lace/.test(out.laceRows[0] || ''),
            `黑色蕾丝 → black lace：${out?.laceRows?.[0]}`],
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
