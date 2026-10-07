把自定义词典丢在这个目录里，ZHTag 启动时会自动全部加载：

  · my.csv   每行：中文,english tag
             同义词：表情包|表情,sticker,meme
  · my.json  {"中文": "english tag"}
  · my.yaml  兼容 sd-webui-prompt-all-in-one 的 group_tags 格式

也支持把社区大词典直接改名丢进来（例如 sd-webui-tagcomplete 的 danbooru.csv）。
改完词典后不用重启整个 ComfyUI：调一下 POST /zhtag/reload 即可生效。

本目录还会自动生成：
  · config.json  兜底翻译配置（fallback / base_url / model …）
  · cache.json   兜底翻译的缓存
