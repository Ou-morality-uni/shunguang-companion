# TTS 接入与选型（2026-10-15）

本次仅调整语音适配、语音设置、播放队列，以及聊天流向语音队列发送事件的连接处。聊天模型调用、记忆、RAG、工具、数据库结构和角色资源不属于本次改动范围。

## 采用的建议与实现

- 回复生成过程中按句提交 TTS，不再等待完整回复。句号、问号、叹号、分号、换行触发切分，长片段最多 180 个 UTF-16 单元，未结束的片段由 700 ms 定时器提交；回复结束时提交余文。
- 当前句和下一句最多提前准备两路合成，播放仍遵循文字顺序。流式返回不改变句子顺序。
- 阿里云、火山：上游 PCM 音频经后端 SSE 送达浏览器，Web Audio 排程播放；完整成功后才生成本机 WAV 供重播。
- 小米克隆：保留官方非流式协议，每句单独合成。参考音频按内容摘要缓存校验、探测及 Base64 编码，最多缓存两份。每次仍读取并检查文件内容，变化后重新准备；这项优化不能省去小米要求的每请求上传。
- 开始新回复、停止回复、切换会话、修改已保存语音配置时，取消请求并清空待播放音频。迟到结果通过播放代次丢弃。已提交给厂商的请求可能已经计费，断开连接不代表撤销费用。
- 不自动切换厂商、不用预置音色兜底，不在收到响应或读超时后自动重试可能计费的请求。

## 配置三家服务

在“陪伴设置 → 声音与播放”中选择厂商。密钥继续由后端凭据机制保护；切换厂商或地址时不继承其他服务的密钥。填写完密钥后点击“保存”，模型列表通过单独按钮读取。

| 服务 | API 地址（只填这里的根地址） | 模型及音色 | 参考音频处理 |
| --- | --- | --- | --- |
| 小米 MiMo | `https://api.xiaomimimo.com/v1` | `mimo-v2.5-tts-voiceclone` | 选择本地 MP3，允许外部参考处理并保存；每句合成均提交参考音频 |
| 阿里云 Qwen | `https://dashscope.aliyuncs.com` 或 `https://dashscope-intl.aliyuncs.com` | 默认 `qwen3-tts-vc-realtime-2026-01-15`，也提供 `2025-11-27` 版本预设；填写匹配的克隆 voice ID | 可填写已有 ID，或使用页面的创建音色按钮；之后只传文字和 ID |
| 火山引擎 | `https://openspeech.bytedance.com` | `seed-tts-2.0-standard`，声音复刻资源 `seed-icl-2.0`，填写已就绪的 speaker ID | 在火山语音控制台完成复刻，本项目不调用训练、购买或音色删除接口 |

阿里云也支持业务空间根域名：`https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com`、`https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com`。音色、模型、API Key 必须匹配账号及地域；音色创建时的 target_model 必须与合成模型一致。

阿里云首次创建音色：选择合规的参考 MP3 → 填写可选参考文字 → 开启“允许创建云端克隆音色”并保存 → 点击“用已保存的参考音频创建音色（一次）” → 获得 ID 后再次保存配置。保存许可开关本身不会上传；创建操作可能产生厂商费用。若创建返回超时，请先查控制台，避免重复创建。已有 ID 无需重新注册。

火山使用新版控制台的 API Key，不是旧版 App ID / Access Token 组合。模型或音色未获授权时会显示错误，不会替换成普通音色。

“播放速度”改变浏览器播放速率；不是厂商合成语速参数。首次播放仍可能受浏览器自动播放政策影响，点击播放后重试即可。

## 哪一家优先

针对这个项目的“中文角色声音复刻 + 低延迟陪伴”，建议优先试 **火山豆包声音复刻 2.0**，以阿里云 Qwen 实时复刻作同样本对照，小米保留为原有参考克隆路线。这个选择依据是火山提供可复用音色及实时音频输出，适合作为后续低延迟语音主线路；**不是三家音质或时延实测冠军的结论**。

阿里云同样具备可复用克隆音色和实时音频能力，最终可能在特定参考声音上更相似。小米官方明确：`voiceclone` 的 streaming 当前是兼容模式，推理完成后才返回，不具备基础 TTS 模型的真正低延迟流式能力。单纯改 `stream=true` 不能解决这一限制。

本次没有使用真实厂商密钥调用或将用户参考录音发送到云端，无法诚实给出“哪家克隆得最像”的实测排名。

## 验证与后续比较

本次通过后端 94 项测试（1 项跳过）、前端 18 项测试，以及类型检查、lint、格式检查与生产构建。新增测试覆盖厂商协议、音频先于终止事件返回、错误脱敏、断流不缓存、参考文件变化、并行合成顺序、PCM 字节跨包、取消和旧代次丢弃。浏览器隔离环境使用测试音，验证了完整回复结束前播放、停止回复后清空音频，以及阿里云和火山的设置分支。

播放面板显示“首音约”：自动朗读从提交消息计时，手动播放从点击计时，直到浏览器开始播放/排程首块音频。PCM 模式含排程等待，不含硬件设备实际发声延迟；静音情况下也会记录调度时间。不要把它当作厂商纯推理耗时。

实际选型时：使用同一份干净单人参考音频、相同的短句/长句/情绪文本、同一网络与播放速度；每家交替测试至少 30 次，分别记录冷启动与连续会话的首音 P50/P95、失败率、停播反应，再盲听比较相似度、自然度、情绪和长句稳定性。成本按控制台实际账单核算。

## 维护入口

- `backend/app/tts_providers.py`：统一合成接口、阿里云 WebSocket、火山 HTTP Chunked、阿里云音色注册。
- `backend/app/voice.py`：小米协议、本地音频、参考缓存、官方地址限制。
- `backend/app/services.py`：语音合成、流式音频、创建音色路由及请求取消。
- `frontend/src/speechStream.ts`：分句、音频 SSE 解码、PCM 排程。
- `frontend/src/useAudioQueue.tsx`：最多预取下一句、顺序播放、重播与取消。
- `frontend/src/useConversation.ts` / `CompanionApp.tsx`：只新增语音用的开始、增量、完成、取消事件连接。

当前每句创建独立上游请求；尚未将整轮回复共用一个长连接。后续只有实测表明连接建立占比显著时，再针对会话连接复用优化。

## 官方依据

- [小米 MiMo TTS 2.5：克隆与流式限制](https://mimo.mi.com/docs/zh-CN/quick-start/usage-guide/audio/speech-synthesis-v2.5)
- [火山 HTTP Chunked / SSE 语音合成](https://docs.volcengine.com/docs/DoubaoVoice/HTTPChunkedSSEUnidirectionalStreaming-V3?lang=zh)
- [火山新版单向流式语音合成](https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http?lang=zh)
- [阿里云声音复刻 HTTP API](https://help.aliyun.com/zh/model-studio/voice-clone-design-http-api)
- [阿里云 WebSocket 接入概览](https://help.aliyun.com/zh/model-studio/realtime-websocket-overview)
- [阿里云 Qwen TTS 客户端事件](https://help.aliyun.com/zh/model-studio/qwen-tts-realtime-client-events)
