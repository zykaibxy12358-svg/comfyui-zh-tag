# ZHTag · ComfyUI 中文提示词插件（v1.2.0）

**像 IDE 一样写提示词**：在文本框里打**中文或拼音**，光标下方直接弹出英文 Danbooru tag 候选，
`↑↓` 选、`Enter`（或 `Tab`）采用、`Esc` 关掉；词库里没有的词给一行「在线翻译」。

```
打 lanfa  →  候选：blue hair（蓝发 · 拼音）      Enter → blue hair,
打 lf     →  候选：blue hair / green hair / …     Enter → 绿发那条
打 蓝发   →  候选：blue hair（蓝发）              Enter → blue hair,
打 long_h →  候选：long_hair / long_horns / …     Enter → long_hair,
```

- **补全**：中文 / 全拼（`lanfa`）/ 首字母（`lf`、`smw`）/ 多音字（`changfa`、`zhangfa` 都查到长发）/ 英文 tag 前缀
- **排序**：匹配质量优先，同质量按 Danbooru 热度 → 最标准的 tag 排最前
- **兜底**：本地查不到 → 候选框出现「在线翻译 → xxx」（LLM/Ollama/在线端点，可一键关掉，关掉就不联网）
- **数据**：3955 条中英词条 + 31171 条 Danbooru 正名/热度 + 26703 字拼音表，全部本地，**零第三方依赖**
- 整句翻译（打中文失焦/停顿自动翻）仍然保留，两种用法可以同时开着

---

## 一、安装

### 方式 A：ComfyUI-Manager（推荐）
Manager → Install via Git URL → 填：
```
https://github.com/zykaibxy12358-svg/comfyui-zh-tag
```

### 方式 B：手动
把 `comfyui-zh-tag` 整个文件夹放进 `ComfyUI/custom_nodes/`，重启 ComfyUI。

装好后控制台会打印：
```
[ZHTag] 词典就绪：3955 条中文词条 / Danbooru 索引 31171 条（来源：danbooru_index.tsv, ts_characters.txt, zh_extra.csv, zh_tags.csv）
[ZHTag] 补全索引就绪：3955 条中文词条 / 拼音表 26703 字 / 英文索引 31171 条
[ZHTag] HTTP 接口已注册：/zhtag/translate, /zhtag/complete, /zhtag/status, /zhtag/reload, /zhtag/dict/download, /zhtag/dict/sources
```

---

## 二、怎么用

### 1）IDE 式补全（默认，最省事）
在**任意文本输入框**（CLIPTextEncode、ZHTag 节点…）里打中文或拼音，候选框就会出现在光标下方：

| 你打的 | 候选（按质量+热度排序） |
| --- | --- |
| `lanfa` | `blue hair`（蓝发） |
| `smw` | `twintails`（双马尾） |
| `changfa` / `zhangfa` | `long hair`（长发，多音字两种拼法都行） |
| `蓝发` / `双马尾` / `一个女孩` | `blue hair` / `twintails` / `1girl` |
| `long_h` | `long_hair`、`long_horns`… |
| `红裙子`（词库里没有） | 先给本地相近词，随后追加「在线翻译 → red skirt」 |

- `↑↓` 移动、`Enter`/`Tab` 采用、`Esc` 关闭；鼠标直接点也行
- 采用后会把**正在打的拼音/中文替换成英文 tag**，并自动补好 `, ` 方便接着打
- 也支持 **Ctrl+Space** 手动唤起；在括号权重里（`(蓝发:1.2)`）照样能补全
- 候选框在**输入法拼字过程中不会弹**（composition 期间静默），选完词立刻弹

### 2）整句翻译（原功能，仍然保留）
打一整句中文，按设置的时机自动翻（默认**失焦时**）：

| 你写的 | 翻出来的 |
| --- | --- |
| `一个蓝发漂亮姑娘` | `blue hair, beautiful, girl` |
| `一个女孩站在樱花树下微笑，长发，黄昏` | `1girl, long hair, smile, standing, tree, cherry blossoms, sunset` |
| `两个女孩手拉手跑过街道` | `2girls, holding hands, running, street` |

| 时机 | 说明 |
| --- | --- |
| `blur`（默认） | 点到别处 / 点运行 时翻译，不打断打字 |
| `idle` | 停止输入 N 毫秒后自动翻译（默认 900ms） |
| `off` | 关闭自动，只用右键菜单或快捷键 |

手动触发：节点右键 →「**中文Tag→英文（本节点全部文本框）**」，或选中节点按 **Ctrl+Alt+T**。

### 3）节点连线
`ZHTag 中文→英文Tag`：中文进，英文出 → 接给 CLIPTextEncode。
它还有第二个输出 **未命中报告**，写着哪些词没查到（方便你补词典）。

`ZHTag 中文CLIP编码`：clip + 中文 → 直接出 CONDITIONING，省一个节点。
`ZHTag 词典查询`：查「双马尾」→ `twintails`，用来验证词库。

### 4）设置项一览

**节点上的输入（顺序不能改，见下方「升级须知」）**

| 位置 | 输入 | 说明 |
| --- | --- | --- |
| 1 | 中文提示词 | 中文/自然语言都行 |
| 2 | 输出模式 | `tags`（逗号分隔）/ `raw`（保留换行） |
| 3 | 去重 | 同一个 tag 只留一次 |
| 4 | 未命中时保留中文 | 默认**关**：没查到的片段丢掉，只写进「未命中报告」 |
| 5 | 用兜底翻译（LLM/在线） | 打开后未命中片段先交给 LLM/在线翻译 |
| 6 | 同义词 | 只输出最佳英文 / 输出全部同义写法 |
| 7 | Danbooru 规范化 | 别名归一到正名并按热度排序 |
| 8 | 未命中处理 | 覆盖第 4、5 项：跟随旧开关 / 丢弃 / 保留 / 交给兜底 |

**前端设置项**

| 设置 | 默认 | 说明 |
| --- | --- | --- |
| **IDE 式补全（打中文/拼音就出候选）** | 开 | 补全总开关 |
| **补全候选数量** | 10 | 候选行数 |
| **词库没有时在候选里给出「在线翻译」** | 开 | 关掉后打字完全不联网 |
| 失焦/停顿时整句翻译 | 开 | 原来的整句翻译开关 |
| 整句翻译的触发时机 | `blur` | `blur` / `idle` / `off` |
| 停顿多久后翻译（毫秒） | 900 | 选 `idle` 时生效 |
| 词典没查到的词怎么办 | `drop` | `drop` 丢掉（推荐）/ `keep` 保留中文原文 / `fallback` 交给兜底翻译 |
| 输出用 Danbooru 正名并按热度排序 | 开 | 关掉就按你输入的顺序、用词典里的原始写法 |
| 整句翻译时走兜底翻译（LLM/在线） | 关 | 打开才会联网/调本地模型 |
| 翻译后弹出提示 | 开 | 每次自动翻译后弹个小提示 |

> **升级须知（v1.1.1 修了一个我自己造成的坑）**：v1.1.0 我把「未命中处理」插在了输入中间，
> 而 ComfyUI 的工作流是**按位置**保存输入值的，结果老工作流把 `True` 塞进了下拉框，
> 点运行时服务端报 `Failed to validate prompt ... Value not in list`。
> v1.1.1 把 v1.0.x 的 6 个输入位置原样恢复，新输入一律追加到最后，
> 并且 BOOLEAN 放前面、COMBO 放最后（BOOLEAN 会被 `bool(val)` 兜住，只有下拉框会因取值不在列表而失败）。
> **老工作流不需要重新搭，直接就能跑。**

---

## 三、翻译优先级（重要）

```
① 本地词典：精确命中 → 繁简归一 → 最长匹配切分（「红色长发」→ 红色 + 长发）
② 数量短语：「两个女孩」→ 2girls、「三个人物」→ 3people
③ 功能词直接丢弃：「一个／的／了／着／她／非常／突然／缓缓地」不会变成 tag
④ 剩余片段按「没查到的词怎么办」处理：drop / keep / fallback
⑤ Danbooru 规范化：别名归一到正名（longhair → long_hair），再按热度排序输出
```

**为什么要有 ③⑤ 这两步**：直接用「中文→英文」的对照表去翻自然语言，会出现
`一个, blue hair, 的漂亮姑娘` 这种结果——量词和「的」被当成 tag，未命中的中文片段也被原样写进提示词。
现在功能词/代词/语气词/程度副词全部过滤，未命中片段默认丢弃（只写进报告），
输出还会按 Danbooru 热度排序，所以最标准、最常被模型识别的 tag 排在最前面。

**权重与括号会被保留**：`(微笑:1.2)` → `(smile:1.2)`；`[[长发]]` → `[[long hair]]`。

**一条中文对应多个英文写法**时，默认只输出最靠前的那个（避免社区词库里的脏别名一起输出）；节点上把「同义词」切成「输出全部同义写法」就会全给。

---

## 四、扩充词库

### 1）右键菜单一键下载社区大词典
节点右键 →「**ZHTag：下载/更新社区词典**」，会从上游拉取并立刻重建词库：

| 来源 | 规模 | 许可 |
| --- | --- | --- |
| BooruTagCart 中文对照表 | 约 5 万条中文 | GPL-3.0 |
| prompt-all-in-one 中文分组表 | 约 3.6 千条 | MIT |
| danbooru-tag-list-zh 角色中文名 | 约 4 万角色 | 仓库未声明 |
| tagcomplete 的 danbooru.csv | 重建正名/热度索引 | MIT |

> 大词典**不随插件打包**（它和你自己的词典一起放在 `data/user/`，属于你的本地数据）：
> 一来 BooruTagCart 是 GPL-3.0，混进 MIT 仓库会造成许可问题；二来几十兆的大表也没必要进包。
> 你也可以完全不下——内置的 3955 条已经覆盖日常出图。

### 2）丢文件进去（离线）
把任意词典文件放进 `comfyui-zh-tag/data/user/`，重启（或调 `POST /zhtag/reload`）即可：

| 格式 | 内容 |
| --- | --- |
| `.csv` / `.txt` | `中文,english tag`，或 `中文[|同义词],english tag[,english tag 2]`（也接受反过来的 `english,中文`） |
| `.json` | `{"中文": "english tag"}` 或 `[{"zh":"…","en":"…"}]` |
| `.yaml` / `.yml` | 兼容 sd-webui-prompt-all-in-one 的 `group_tags` 格式（`tags:` 下的 `英文: 中文`） |

示例 `data/user/my.csv`：
```
# 我的词典
我的自定义词,my custom tag
表情包|表情,sticker,meme
```

---

## 五、兜底翻译怎么配

编辑 `comfyui-zh-tag/data/user/config.json`（首次运行自动生成）：

```json
{
  "fallback": "llm",
  "base_url": "http://127.0.0.1:11434/v1",
  "api_key": "",
  "model": "qwen2.5:7b",
  "timeout": 20
}
```

- `fallback`：`keep`（默认，保留中文）/ `llm`（OpenAI 兼容接口）/ `google`（免 key 的在线端点，可能不稳）
- `base_url`：任何 OpenAI 兼容服务都行——**Ollama**（`http://127.0.0.1:11434/v1`）、**LM Studio**（`http://127.0.0.1:1234/v1`）、DeepSeek/OpenAI（填官方地址 + `api_key`）
- 翻译结果会缓存到 `data/user/cache.json`，同一个词只翻一次；连不上时静默失败（不会卡住跑图）
- 只在「没查到的词怎么办 = fallback」且「用兜底翻译」都打开时才会真的调用

---

## 六、接口（前端在用，也可以自己调）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/zhtag/complete` | `?q=lanfa&limit=10` → `{results:[{en, zh, score, count, kind}]}`（中文/拼音/英文补全） |
| POST | `/zhtag/translate` | `{text, mode, fallback, unknownMode, normalize, firstOnly}` → `{english, unknown, dropped, function, info}` |
| GET | `/zhtag/status` | 词库条数、来源文件、兜底配置、社区词典下载状态 |
| POST | `/zhtag/reload` | 重新加载 `data/` 与 `data/user/` 下所有词典文件（补全索引一起重建） |
| POST | `/zhtag/dict/download` | `{ids?, defaultOnly?}` 下载/更新社区词典并热重载 |
| GET | `/zhtag/dict/sources` | 可下载的词典源清单 |

自测：
```bash
curl "http://127.0.0.1:8188/zhtag/complete?q=lanfa"       # → blue hair（蓝发）
curl "http://127.0.0.1:8188/zhtag/complete?q=smw"         # → twintails（双马尾）
curl -X POST http://127.0.0.1:8188/zhtag/translate -H "Content-Type: application/json" -d "{\"text\":\"一个蓝发漂亮姑娘站在樱花树下微笑\"}"
# → {"ok":true,"english":"smile, standing, blue hair, tree, cherry blossoms, beautiful, girl", ...}
```

---

## 七、自测（都不需要 ComfyUI）

```bash
python comfyui-zh-tag/tests/test_dictionary.py   # 后端 87 项
node   comfyui-zh-tag/tests/test_frontend.mjs    # 前端 58 项
```

**后端 87 项**：词典加载、精确/同义词、繁简归一、最长匹配切分、权重括号保留、去重、
自然语言整句、功能词/人称代词/数量短语、`unknown_mode` 三种策略、
Danbooru 正名与热度排序、兜底链路（含连不上时的安全失败）、自定义词典加载、
配置文件/拼音表不被误当词典、节点层默认设置、**老工作流位置兼容**（复刻前端按位置映射
widgets_values，含现有工作流那份真实取值）、
**补全引擎**（全拼/首字母/多音字/中文精确/英文前缀/排序/limit/耗时）、性能（整句 0.5 ms、补全 2 ms）。

**前端 58 项**：在临时目录里搭出 `<tmp>/scripts/app.js` 桩 + 极简 DOM 桩 + 真实的 `zhtag.js`，验证
注册与 10 项设置、失焦自动翻译并写回、不重复翻译、纯英文不触发、右键菜单注入与点击（含下载词典）、
`Ctrl+Alt+T`、设置变化同步进请求体，以及**补全交互**：片段识别（逗号/权重/光标位置）、
触发条件（中文 1 字、拼音 2 字母起）、候选框渲染（tag+来源+热度）、`↑↓` 选择、`Enter` 替换并补分隔符、
`Esc` 关闭、鼠标点选、中文输入、本地没有时追加「在线翻译」、关掉联网后零请求。

---

## 八、词库来源与许可

- 内置 `data/zh_tags.csv` 由 **[sd-webui-prompt-all-in-one](https://github.com/Physton/sd-webui-prompt-all-in-one)** 的 `group_tags/zh_CN.yaml`（MIT License）派生。
- `data/zh_extra.csv` 是本插件自己补充的常用词（自然语言动作/姿态/风格，MIT）。
- `data/danbooru_index.tsv` 由 **[a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete)** 的 `tags/danbooru.csv`（MIT）派生，只保留 general/meta 标签的正名、热度与别名。
- `data/ts_characters.txt` 来自 **[OpenCC](https://github.com/BYVoid/OpenCC)** 的 `TSCharacters.txt`（Apache-2.0），用于繁体输入归一为简体。
- `data/pinyin_chars.tsv` 由 **[pypinyin](https://github.com/mozillazg/python-pinyin)**（MIT）在本机构建期生成，**运行时零依赖**；`_build/build_pinyin_table.py` 是生成脚本。
- 社区词典（GPL-3.0 等）仅由 `py/sources.py` 在你本机运行时下载到 `data/user/`，不随本插件分发。
- 本插件代码：MIT。

---

## 九、开发注意（踩过的坑）

1. **前端 import 的层级**：`web/js/zhtag.js` 里必须写 `../../../scripts/app.js`（不是 `../../`）。
   URL 空间是 `/extensions/<插件目录名>/js/zhtag.js`，`../../` 只会走到 `/extensions/` → 404，
   整个扩展会静默失效。放在 `web/` 根目录的文件才用 `../../`。
2. **`settings` 数组里不能有 `undefined`**：新版前端（1.45+）会遍历该数组注册设置，
   写 `settings: [addSetting(...)]` 这种"顺便注册"的写法会炸。正确做法是只返回设置对象。
3. **`/scripts/app.js` 在新前端是个 shim**：它从 `window.comfyAPI.app.app` 转出 `app`，
   所以 `import { app } from ".../scripts/app.js"` 仍然可用。
4. 后端模块要能在没有 ComfyUI 的环境下导入（`routes.py` 里拿不到 `server` 就跳过注册），
   这样单测才能脱离 ComfyUI 跑。
5. **拼音要「多读音变体」**：`长` = zhǎng/cháng，只取第一个读音的话 `changfa` 查不到长发；
   `py/complete.py` 对每个字做读音笛卡尔积（上限 8 个变体），所以 `changfa` 和 `zhangfa` 都能命中。
6. **补全弹层不能抢焦点**：用 `mousedown` + `preventDefault`，否则点候选框会先 blur 掉 textarea；
   光标定位用「镜像 div + 标记 span」量坐标（textarea 里唯一可靠的办法），量不准就退化成贴在框下方。
7. **输入法**：`compositionstart` 时先关候选框，`compositionend` 再弹，否则选词过程中会一直闪。
