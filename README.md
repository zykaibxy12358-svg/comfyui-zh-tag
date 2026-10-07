# ZHTag · ComfyUI 中文提示词插件

**在文本框里打中文，自动对照 tag 词典翻成英文 tag**；词典没有的片段走兜底翻译（本地/在线 LLM），再兜不住就保留中文——**绝不丢信息**。

- 节点：`ZHTag 中文→英文Tag` / `ZHTag 中文CLIP编码` / `ZHTag 词典查询`
- 前端：给所有文本输入框加**失焦自动翻译**、右键菜单「中文Tag→英文」、快捷键 `Ctrl+Alt+T`
- 词库：内置 **3640 条**中文词条 + 繁→简自动归一（5062 字表），`data/user/` 里丢文件即可扩充
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
[ZHTag] 词典就绪：3640 条中文词条（来源：ts_characters.txt, zh_tags.csv）
[ZHTag] HTTP 接口已注册：/zhtag/translate, /zhtag/status, /zhtag/reload
```

---

## 二、怎么用

### 1）文本框直接输入中文（最省事）
在 **CLIPTextEncode** 或 `ZHTag 中文→英文Tag` 节点的文本框里打中文：

```
一个女孩站在樱花树下微笑，长发，黄昏，电影感光线，高质量，杰作
```

按设置里的时机触发（默认**失焦时**，也就是点到别处就翻），文本框内容变成：

```
1girl, girl, standing, cherry blossoms, tree, smile, long hair, dusk, cinematic lighting, high quality, masterpiece
```

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
`ZHTag 词典查询`：查「双马尾」→ `bunches, twintails`，用来验证词库。

---

## 三、翻译优先级（重要）

```
① 内置/自定义词典（精确 → 繁简归一 → 最长匹配切分）
② 兜底翻译：缓存 → LLM（OpenAI 兼容）→ 在线翻译（默认关）
③ 保留中文原文（默认，绝不丢词）
```

**最长匹配切分**是关键：词库里没有「红色长发」这个整词，也会拆成 `红色` + `长发` → `red, long hair`。

**权重与括号会被保留**：`(微笑:1.2)` → `(smile:1.2)`；`[[长发]]` → `[[long hair]]`。

**一条中文对应多个英文写法**时，默认只输出最靠前的那个（避免社区词库里的脏别名一起输出）；节点上把「同义词」切成「输出全部同义写法」就会全给。

---

## 四、兜底翻译怎么配

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
- 翻译结果会缓存到 `data/user/cache.json`，同一个词只翻一次；连不上时静默失败并保留中文（不会卡住跑图）

节点上的开关「**用兜底翻译（LLM/在线）**」默认关——想省时间就关着，只靠词典；想一个词都不留中文就打开。

---

## 五、扩充词库

把任意词典文件丢进 `comfyui-zh-tag/data/user/`，重启（或调 `POST /zhtag/reload`）即可，支持：

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

## 六、接口（前端在用，也可以自己调）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/zhtag/translate` | `{text, mode, fallback, firstOnly}` → `{english, unknown, info}` |
| GET | `/zhtag/status` | 词库条数、来源文件、兜底配置 |
| POST | `/zhtag/reload` | 重新加载 `data/` 与 `data/user/` 下所有词典文件 |

自测：
```bash
curl -X POST http://127.0.0.1:8188/zhtag/translate -H "Content-Type: application/json" -d "{\"text\":\"双马尾女孩微笑\"}"
```

---

## 七、自测（不需要 ComfyUI）

```bash
python comfyui-zh-tag/tests/test_dictionary.py
```
23 项断言：词典加载、精确/同义词、繁简归一、最长匹配切分、权重保留、去重、未命中保留、兜底链路（含连不上时的安全失败）、自定义词典加载、性能（单次整句 < 1ms）。

---

## 八、词库来源与许可

- 内置 `data/zh_tags.csv` 由 **[sd-webui-prompt-all-in-one](https://github.com/Physton/sd-webui-prompt-all-in-one)** 的 `group_tags/zh_CN.yaml`（MIT License）派生，另加本插件补充的常用词与画质/构图/光照类词条。
- `data/ts_characters.txt` 来自 **[OpenCC](https://github.com/BYVoid/OpenCC)** 的 `TSCharacters.txt`（Apache-2.0），用于繁体输入归一为简体。
- 本插件代码：MIT。
