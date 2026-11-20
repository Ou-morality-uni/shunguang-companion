# 瞬光伴行 v0.7.8

## 阿里云百炼国际站新加坡

- 在「陪伴设置 → 模型连接」选择「阿里云百炼 · 国际站新加坡」。公共地址为 `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`。工作空间专属地址同样需要保留 `/compatible-mode/v1`。如果读取不到模型列表，可以填写实际模型 ID，再保存并测试连接。[阿里云聊天接口](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions)
- 在「陪伴设置 → 声音与播放」选择同名语音预设。公共地址为 `https://dashscope-intl.aliyuncs.com`，工作空间专属地址填写 HTTPS 根地址。默认模型为 `qwen-audio-3.1-tts-flash`，也可填写项目已适配且账号可用的模型。保存后可检查连接，再填入当前地址的音色 ID 或创建新音色并试听。[阿里云 Qwen-Audio TTS 接口](https://www.alibabacloud.com/help/en/model-studio/qwen-audio-tts-websocket-api)
- 北京预设继续可用。聊天与语音使用各自配置的 API Key，切换公共地址或工作空间时使用目标地址对应的密钥。云端音色还需与账号及模型匹配。[阿里云音色复刻接口](https://www.alibabacloud.com/help/en/model-studio/voice-clone-design-http-api.md)

本版沿用已有依赖。离线验收覆盖地址与密钥隔离、合成和音色请求，实际模型与音色权限可在自己的新加坡账号中测试。
