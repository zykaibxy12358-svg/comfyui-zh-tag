# ZHTag · ComfyUI 中文提示词插件（v1.1.0）

**在文本框里打中文——写词组也行，写一整句大白话也行——自动变成干净的英文 Danbooru tag。**

```
一个蓝发漂亮姑娘站在樱花树下微笑
        ↓
smile, standing, blue hair, tree, cherry blossoms, beautiful, girl
```

- 节点：`ZHTag 中文→英文Tag` / `ZHTag 中文CLIP编码` / `ZHTag 词典查询`
- 前端：所有文本输入框**失焦自动翻译** + 右键菜单「中文Tag→英文」 + 快捷键 `Ctrl+Alt+T`
- 词库：内置 **3955 条**中文词条 + **31171 条** Danbooru 正名/热度索引 + 繁→简归一（4148 字）
- 质量：自动过滤「一个／的／她／非常／突然」这类功能词，输出统一用 Danbooru 正名并**按热度排序**
- 零第三方依赖（只用标准库），纯离线可用

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
[ZHTag] HTTP 接口已注册：/zhtag/translate, /zhtag/status, /zhtag/reload, /zhtag/dict/download, /zhtag/dict/sources
```

---

## 二、怎么用

### 1）文本框直接输入中文（最省事）
在 **CLIPTextEncode** 或 `ZHTag 中文→英文Tag` 节点的文本框里打中文，按设置里的时机触发
（默认**失焦时**，点到别处就翻）：

| 你写的 | 翻出来的 |
| --- | --- |
| `一个蓝发漂亮姑娘` | `blue hair, beautiful, girl` |
| `一个女孩站在樱花树下微笑，长发，黄昏` | `1girl, long hair, smile, standing, tree, cherry blossoms, sunset` |
| `两个女孩手拉手跑过街道` | `2girls, holding hands, running, street` |
| `白发少女抱着猫坐在椅子上闭着眼睛微笑` | `smile, closed eyes, white hair, holding cat, girl, sitting on chair` |

三种触发方式（设置里可切换）：
| 时机 | 说明 |
| --- | --- |
| `blur`（默认） | 点到别处 / 点运行 时翻译，不打断打字 |
| `idle` | 停止输入 N 毫秒后自动翻译（默认 900ms） |
| `off` | 关闭自动，只用右键菜单或快捷键 |

手动触发：
- 节点右键 →「**中文Tag→英文（本节点全部文本框）**」
- 选中节点后按 **Ctrl+Alt+T**
- 文本框内按 **Ctrl+Alt+T**（焦点在框里时）

### 2）节点连线
`ZHTag 中文→英文Tag`：中文进，英文出 → 接给 CLIPTextEncode。
它还有第二个输出 **未命中报告**，写着哪些词没查到（方便你补词典）。

`ZHTag 中文CLIP编码`：clip + 中文 → 直接出 CONDITIONING，省一个节点。
`ZHTag 词典查询`：查「双马尾」→ `twintails`，用来验证词库。

### 3）设置项一览

| 设置 | 默认 | 说明 |
| --- | --- | --- |
| 自动把中文翻成英文Tag | 开 | 总开关 |
| 自动触发时机 | `blur` | `blur` / `idle` / `off` |
| 停顿多久后翻译（毫秒） | 900 | 选 `idle` 时生效 |
| **词典没查到的词怎么办** | `drop` | `drop` 丢掉（推荐，出图更干净）/ `keep` 保留中文原文 / `fallback` 交给兜底翻译 |
| **输出用 Danbooru 正名并按热度排序** | 开 | 关掉就按你输入的顺序、用词典里的原始写法 |
| 词库没有时走兜底翻译（LLM/在线） | 关 | 打开才会联网/调本地模型 |
| 翻译后弹出提示 | 开 | 每次自动翻译后弹个小提示 |

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
| POST | `/zhtag/translate` | `{text, mode, fallback, unknownMode, normalize, firstOnly}` → `{english, unknown, dropped, function, info}` |
| GET | `/zhtag/status` | 词库条数、来源文件、兜底配置、社区词典下载状态 |
| POST | `/zhtag/reload` | 重新加载 `data/` 与 `data/user/` 下所有词典文件 |
| POST | `/zhtag/dict/download` | `{ids?, defaultOnly?}` 下载/更新社区词典并热重载 |
| GET | `/zhtag/dict/sources` | 可下载的词典源清单 |

自测：
```bash
curl -X POST http://127.0.0.1:8188/zhtag/translate -H "Content-Type: application/json" -d "{\"text\":\"一个蓝发漂亮姑娘站在樱花树下微笑\"}"
# → {"ok":true,"english":"smile, standing, blue hair, tree, cherry blossoms, beautiful, girl", ...}
```

---

## 七、自测（都不需要 ComfyUI）

```bash
python comfyui-zh-tag/tests/test_dictionary.py   # 后端 55 项
node   comfyui-zh-tag/tests/test_frontend.mjs    # 前端 28 项
```

**后端 55 项**：词典加载、精确/同义词、繁简归一、最长匹配切分、权重括号保留、去重、
自然语言整句、功能词/人称代词/数量短语、`unknown_mode` 三种策略、
Danbooru 正名与热度排序、兜底链路（含连不上时的安全失败）、自定义词典加载、
配置文件不被误当词典、性能（单次整句 0.5 ms）。

**前端 28 项**：在临时目录里搭出 `<tmp>/scripts/app.js` 桩 + 真实的 `zhtag.js`，验证
注册与 7 项设置（含"settings 里不能有 undefined"这类新版前端的坑）、失焦自动翻译并写回、
不重复翻译、纯英文不触发、右键菜单注入与点击（含下载词典）、`Ctrl+Alt+T` 快捷键、
设置变化会同步进请求体。

---

## 八、词库来源与许可

- 内置 `data/zh_tags.csv` 由 **[sd-webui-prompt-all-in-one](https://github.com/Physton/sd-webui-prompt-all-in-one)** 的 `group_tags/zh_CN.yaml`（MIT License）派生。
- `data/zh_extra.csv` 是本插件自己补充的常用词（自然语言动作/姿态/风格，MIT）。
- `data/danbooru_index.tsv` 由 **[a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete)** 的 `tags/danbooru.csv`（MIT）派生，只保留 general/meta 标签的正名、热度与别名。
- `data/ts_characters.txt` 来自 **[OpenCC](https://github.com/BYVoid/OpenCC)** 的 `TSCharacters.txt`（Apache-2.0），用于繁体输入归一为简体。
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
