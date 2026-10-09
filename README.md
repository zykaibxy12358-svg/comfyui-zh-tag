# ZHTag · ComfyUI 中文提示词插件（v1.2.4）

**像 IDE 一样写提示词**：在文本框里打**中文、拼音或英文词**，光标下方直接弹出英文 Danbooru tag 候选，
`↑↓` 选、`Enter`（或 `Tab`）采用、`Esc` 关掉；词库里没有的词给一行「在线翻译」。

```
打 lanfa    →  候选：blue hair（蓝发 · 拼音）        Enter → blue hair,
打 breasts  →  候选：breasts / large breasts / **huge breasts** / …
打 巨大乳房  →  候选：huge breasts（词组，真实标签 209k）
打 黑色蕾丝  →  候选：black lace（词组）              Enter → black lace,
打 白色连衣裙 →  候选：white dress（词组，真实标签 267k）
```

- **补全**：中文 / 拼音全拼（`lanfa`）/ 拼音首字母（`lf`、`smw`）/ 多音字（`changfa`、`zhangfa`）/ 英文 tag 前缀（`long_h`）
- **全词联想**：输入 `breasts` → `large breasts`、`huge breasts`；`hair` → `long hair`、`blonde hair`；`dress` → `white dress`、`black dress`
- **词组制度**：中文两三个词直接拼成真实 tag —— `巨大乳房`→`huge breasts`、`白色连衣裙`→`white dress`（带 Danbooru 热度）；查不到的组合也会现场拼出短语（`黑色蕾丝`→`black lace`）
- **排序**：匹配质量优先，同质量按 Danbooru 热度 → 最标准的 tag 排最前
- **兜底**：本地查不到 → 候选框出现「在线翻译 → xxx」；**词典 / 谷歌 / 微软 / 百度 / 有道 一键切换**（带状态灯，百度有道填自己的 key）
- **数据**：4000+ 条中英词条 + 31171 条 Danbooru 正名/热度 + 26703 字拼音表 + 1.6 万词联想索引 + 4900+ 条中文词组，全部本地，**零第三方依赖**
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
| `long_h` | `long hair`、`long horns`… |
| `breasts` | `breasts`、`large breasts`、`medium breasts`、`huge breasts`…（英文整词联想） |
| `巨大乳房` | `huge breasts`（词组，真实 Danbooru 标签，热度 209k） |
| `白色连衣裙` | `white dress`（词组，真实标签 267k） |
| `黑色蕾丝` | `black lace`（词组，现场拼出来的短语） |
| `红裙子` | `red skirt`（词库里只有「红裙」，也会给出候选） |
| `霓虹灯牌`（词库里没有） | 先显示「正在用谷歌翻译…」，随后出现「在线翻译 → neon lights」 |

- `↑↓` 移动、`Enter`/`Tab` 采用、`Esc` 关闭；鼠标直接点也行
- 采用后会把**正在打的拼音/中文替换成英文 tag**，并自动补好 `, ` 方便接着打
- 也支持 **Ctrl+Space** 手动唤起；在括号权重里（`(蓝发:1.2)`）照样能补全
- 候选框在**输入法拼字过程中不会弹**（composition 期间静默），选完词立刻弹
- 候选框**右上角有「在线：谷歌 / 微软」按钮**：点一下即切换在线翻译服务商（写回后端配置，重启也记得），
  按钮上的 `●` / `✗` 是上次连通状态；右键菜单里也有一个切换项，设置面板里也有同名下拉

### 2）放在子图（子工作流）里怎么用 ⚠️
ComfyUI 的规矩是：**一个输入口一旦接了线，对应的文本框就会被藏起来**（值由连线决定）。
子图里还有一个坑：如果你把 ZHTag 的「中文提示词」**提升成子图输入**，再把那个口连上线，
那么父节点上的文本框和内层文本框会**双双被隐藏**——图上一个能打字的地方都没有。

所以节点专门留了一个**纯插口输入「提示词(连线优先)」**（只做插口，不占文本框位置）：

| 想干的事 | 正确做法 |
| --- | --- |
| 在子图里手打中文 | 让「中文提示词」保持为普通文本框，**不要**提升/连线它 |
| 从子图外面喂提示词 | 提升并连线 **「提示词(连线优先)」** 这个口；文本框依旧能打字，接了线时以线为准 |
| 已经连错、现在打不了字 | 在子图里右键那条连到「中文提示词」的线把它删掉；或右键输入口 → 取消/转回小部件 |

优先级：**「提示词(连线优先)」有线 → 用线里的内容；没线 → 用文本框内容。**

### 3）整句翻译（原功能，仍然保留）
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

### 4）节点连线
`ZHTag 中文→英文Tag`：中文进，英文出 → 接给 CLIPTextEncode。
它还有第二个输出 **未命中报告**，写着哪些词没查到（方便你补词典）。

`ZHTag 中文CLIP编码`：clip + 中文 → 直接出 CONDITIONING，省一个节点。
`ZHTag 词典查询`：查「双马尾」→ `twintails`，用来验证词库。

### 5）设置项一览

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
| 🔌 | 提示词(连线优先) | 纯插口（不占小部件位置）：接了线就用线里的内容。**子图里连这个口，别连文本框** |

**前端设置项**

| 设置 | 默认 | 说明 |
| --- | --- | --- |
| IDE 式补全（打中文/拼音就出候选） | 开 | 补全总开关 |
| 补全候选数量 | 10 | 候选行数 |
| 整句翻译时词典没查到的词怎么办 | `drop` | `drop` 丢掉 / `keep` 保留中文 / `fallback` 交给翻译方式 |
| **翻译方式** | `google` | `off` 只用词典（不联网）/ `google` / `microsoft` / `baidu` / `youdao` / `llm` |
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

## 三、匹配优先级（重要）

```
① 中文精确命中        蓝发 → blue hair                       100 分
② 中文词组（真实标签） 巨大乳房 → huge breasts（209k）          98 分
③ 中文词组（拼装）     黑色蕾丝 → black lace                    88 分
④ 拼音（全拼/首字母，含多音字变体）  lanfa / smw / changfa      95/90 分
⑤ 英文 tag 精确        breasts → breasts                      85 分
⑥ 中文前缀            双马 → 双马尾…                          80 分
⑦ 英文整词联想         breasts → large breasts / huge breasts   72/66/62 分
⑧ 拼音前缀 / 英文前缀   lanf → 蓝发；long_h → long hair         70/55 分
⑨ 在线翻译            词库完全没有的词                         兜底
```

**词组制度怎么来的**（全部本机、零依赖、启动时 0.2 秒建好）：

1. **单词级映射**：直接取词典里本来就是单词的条目（`蕾丝→lace`、`乳房→breasts`），
   并把「红发→red hair」这类 1:1 条目**按字对词对齐**，攒出 `白↔white`、`发↔hair`（带投票去歧义）
2. **拼装**：拿 Danbooru 索引里的 2~3 词标签（`white_thighhighs`），用上面的表把每个英文词换成中文再拼起来
   → 得到「中文词组 → 真实 Danbooru 标签」的对照表，**自带热度**，不用人工写几万条
3. **现场拆词**：对照表里没有的，就把你打的这句话按词典切成词、按顺序拼成英文短语
   （`黑色蕾丝` → `black` + `lace` → `black lace`）

**全词联想**用的是同一份 Danbooru 索引：把每个 tag 按 `_` 切成词建倒排索引，
所以打 `breasts` 能联想到 `large breasts`、`huge breasts`，打 `dress` 能联想到 `white dress`、`black dress`。
修饰词在前的（`huge_breasts`）比别的（`breasts_squeeze`）分更高，同分按热度排。

---

## 四、整句翻译（原功能，仍然保留）

**为什么要过滤功能词、又要做 Danbooru 规范化**：直接用「中文→英文」的对照表去翻自然语言，会出现
`一个, blue hair, 的漂亮姑娘` 这种结果——量词和「的」被当成 tag，未命中的中文片段也被原样写进提示词。
现在功能词/代词/语气词/程度副词全部过滤，未命中片段默认丢弃（只写进报告），
输出还会按 Danbooru 热度排序，所以最标准、最常被模型识别的 tag 排在最前面。

拆词顺序是：精确命中 → 繁简归一 → 最长匹配切分（「红色长发」→ 红色 + 长发）→ 数量短语（「两个女孩」→ 2girls）
→ 剩余片段按「没查到的词怎么办」处理：`drop` / `keep` / `fallback`。

**权重与括号会被保留**：`(微笑:1.2)` → `(smile:1.2)`；`[[长发]]` → `[[long hair]]`。

**一条中文对应多个英文写法**时，默认只输出最靠前的那个（避免社区词库里的脏别名一起输出）；节点上把「同义词」切成「输出全部同义写法」就会全给。

---

## 五、扩充词库

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
> 你也可以完全不下——内置的 4000+ 条已经覆盖日常出图。

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

## 六、在线翻译怎么配 / 怎么切

**最省事**：不用改任何文件——补全弹层右上角点「谷歌」或「微软」即可，配置会自动写回
`comfyui-zh-tag/data/user/config.json`，重启也记得。

也可以直接编辑 `data/user/config.json`（首次运行自动生成）：

```json
{
  "fallback": "google",
  "timeout": 20,
  "exec_timeout": 6,
  "baidu_appid": "",
  "baidu_key": "",
  "youdao_appid": "",
  "youdao_key": "",
  "base_url": "http://127.0.0.1:11434/v1",
  "api_key": "",
  "model": "qwen2.5:7b"
}
```

- `fallback` 就是弹层右上角那个开关：`off`（只用词典，不联网）/ `google` / `microsoft` / `baidu` / `youdao` / `llm`
- **免 key 的两家**：谷歌（`translate.googleapis.com`）、微软（Edge 翻译接口）
- **要自己填 key 的两家**：
  - 百度 → [百度翻译开放平台](https://fanyi-api.baidu.com) 申请「通用文本翻译」，把 `appid` 填 `baidu_appid`、密钥填 `baidu_key`
  - 有道 → [有道智云](https://ai.youdao.com) 创建「文本翻译」应用，`应用ID` 填 `youdao_appid`、`应用密钥` 填 `youdao_key`
  - 没填 key 时按钮上显示 `·`，点它会提示去哪填，**不会发请求、也不会让跑图干等**
- `llm`：`base_url` 支持任何 OpenAI 兼容服务（Ollama `http://127.0.0.1:11434/v1`、LM Studio `http://127.0.0.1:1234/v1`、DeepSeek/OpenAI…）
- 弹层按钮上的 `●` = 上次正常，`✗` = 上次失败，`·` = 还没配 key
- 翻译结果缓存到 `data/user/cache.json`，同一个词只翻一次；切翻译方式时会清掉失败记录重试

### 跑图不想等翻译？（v1.2.4 重点）

| 你想要的 | 怎么做 |
| --- | --- |
| 完全不等、只用词典 | 弹层右上角点**「词典」**（或设置里把翻译方式选 `off`）——一个字都不联网 |
| 输入的是英文，不该等待 | 已经是这样了：**纯英文/纯 tag 输入直接原样通过，不联网不拆词**（`1girl, long hair` 原样保留） |
| 想联网但别等太久 | 节点执行时的网络超时是 `exec_timeout`（默认 **6 秒**，打字时才是 20 秒） |
| 跑图卡在翻译上想强行终止 | **按 ComfyUI 的「中断」**：翻译会立刻放弃（不再等网络），跑图马上结束 |
| 一个词连不上，别拖累后面的 | 一轮执行里翻译**失败一次就不再试**，所以最多只等一次超时 |

> 内核里还做了一件事：节点执行时会把 ComfyUI 的中断回调接进翻译器，
> 所以「中断」对翻译也是有效的，而不是要等 `urllib` 超时。

---

## 七、接口（前端在用，也可以自己调）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/zhtag/complete` | `?q=lanfa&limit=10` → `{results:[{en, zh, score, count, kind}]}`（中文/拼音/英文补全） |
| GET | `/zhtag/online` | 当前翻译方式 + 各家配置/连通状态；`?test=baidu` 可顺手测一次 |
| POST | `/zhtag/online` | `{mode:'off'\|'google'\|'microsoft'\|'baidu'\|'youdao'\|'llm', test?:true}` 切换并写回配置 |
| GET | `/zhtag/config` | 翻译相关配置（key 只回「填没填」，不回明文） |
| POST | `/zhtag/translate` | `{text, mode, fallback, unknownMode, normalize, firstOnly}` → `{english, unknown, dropped, function, info}` |
| GET | `/zhtag/status` | 词库条数、来源文件、兜底配置、社区词典下载状态 |
| POST | `/zhtag/reload` | 重新加载 `data/` 与 `data/user/` 下所有词典文件（补全索引一起重建） |
| POST | `/zhtag/dict/download` | `{ids?, defaultOnly?}` 下载/更新社区词典并热重载 |
| GET | `/zhtag/dict/sources` | 可下载的词典源清单 |

自测：
```bash
curl "http://127.0.0.1:8188/zhtag/complete?q=lanfa"       # → blue hair（蓝发）
curl "http://127.0.0.1:8188/zhtag/complete?q=smw"         # → twintails（双马尾）
curl "http://127.0.0.1:8188/zhtag/online"                 # → 当前用的是谷歌还是微软
curl -X POST http://127.0.0.1:8188/zhtag/online -H "Content-Type: application/json" -d "{\"mode\":\"microsoft\",\"test\":true}"
curl -X POST http://127.0.0.1:8188/zhtag/translate -H "Content-Type: application/json" -d "{\"text\":\"一个蓝发漂亮姑娘站在樱花树下微笑\"}"
# → {"ok":true,"english":"smile, standing, blue hair, tree, cherry blossoms, beautiful, girl", ...}
```

---

## 八、自测（都不需要 ComfyUI）

```bash
python comfyui-zh-tag/tests/test_dictionary.py   # 后端 137 项
node   comfyui-zh-tag/tests/test_frontend.mjs    # 前端 90 项
node   comfyui-zh-tag/tests/e2e_complete.mjs     # 真浏览器端到端 20 项（需 ComfyUI 8188 + Chrome 9222）
```

**后端 137 项**：词典加载、精确/同义词、繁简归一、最长匹配切分、权重括号保留、去重、
自然语言整句、功能词/人称代词/数量短语、`unknown_mode` 三种策略、
**切分残留的单字不送在线翻译**、Danbooru 正名与热度排序、兜底链路（含连不上时的安全失败）、
**在线服务商切换与写回配置**、自定义词典加载、配置文件/拼音表不被误当词典、节点层默认设置、
**老工作流位置兼容**、**补全引擎**（全拼/首字母/多音字/中文精确/英文前缀/排序/limit/耗时）、
性能（整句 0.5 ms、补全 2 ms）。

**前端 90 项**：在临时目录里搭出 `<tmp>/scripts/app.js` 桩 + 极简 DOM 桩 + 真实的 `zhtag.js`，验证
注册与 11 项设置、失焦自动翻译并写回、不重复翻译、纯英文不触发、右键菜单注入与点击（含下载词典）、
`Ctrl+Alt+T`、设置同步，以及**补全交互**：片段识别、触发条件、候选框渲染、`↑↓` 选择、
`Enter` 替换并补分隔符、`Esc`、鼠标点选、中文输入、在线翻译、「没开在线翻译」提示、
**谷歌/微软切换按钮**（立刻生效 + 后台测连通 + 状态灯 + 反馈）。

**E2E 20 项**：用 Chrome DevTools Protocol 在**真实浏览器**里跑一遍（已在 ComfyUI 0.39.2 + 前端 1.53.10 上跑过）：候选框按光标定位、
`Enter` 替换、中文候选、词库没有的词经**谷歌真翻译**（霓虹灯牌 → neon lights）并采用、
右上角按钮切微软 → 立刻高亮 → 后台测出连不上显示 `✗` → 切回谷歌。

---

## 九、词库来源与许可

- 内置 `data/zh_tags.csv` 由 **[sd-webui-prompt-all-in-one](https://github.com/Physton/sd-webui-prompt-all-in-one)** 的 `group_tags/zh_CN.yaml`（MIT License）派生。
- `data/zh_extra.csv` 是本插件自己补充的常用词（自然语言动作/姿态/风格，MIT）。
- `data/danbooru_index.tsv` 由 **[a1111-sd-webui-tagcomplete](https://github.com/DominikDoom/a1111-sd-webui-tagcomplete)** 的 `tags/danbooru.csv`（MIT）派生，只保留 general/meta 标签的正名、热度与别名。
- `data/ts_characters.txt` 来自 **[OpenCC](https://github.com/BYVoid/OpenCC)** 的 `TSCharacters.txt`（Apache-2.0），用于繁体输入归一为简体。
- `data/pinyin_chars.tsv` 由 **[pypinyin](https://github.com/mozillazg/python-pinyin)**（MIT）在本机构建期生成，**运行时零依赖**；`_build/build_pinyin_table.py` 是生成脚本。
- 社区词典（GPL-3.0 等）仅由 `py/sources.py` 在你本机运行时下载到 `data/user/`，不随本插件分发。
- 本插件代码：MIT。

---

## 十、开发注意（踩过的坑）

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
8. **子图里「被连线的小部件」会被 ComfyUI 藏起来**（`display:none` + `pointer-events:none`）。
   所以别把「中文提示词」这种文本框提升成子图输入；要连线就用单独的 `forceInput` 插口
   （本插件的「提示词(连线优先)」就是干这个的）。实测：提升文本框并连线后，
   父节点和内层的文本框会同时被隐藏，图上一个能打字的地方都没有。
9. **前端 1.5x 的 DOM 小部件**：`DOMWidgetImpl` 常常只有 `element` 没有 `inputEl`，
   而且提升小部件是节点建好之后才加上去的——所以绑定要 `inputEl || element`，
   并在 `onDrawForeground` 里补装饰（绝不能退化成「随便找一个 textarea 绑上去」）。
