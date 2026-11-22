"""Developer-maintained turn capability statements."""

from . import stickers
from .constants import MAX_TOOL_CALLS


def turn_capabilities(schemas, sticker_catalog, is_local):
    return (
        '用户事实与实际记忆操作结果在参考数据中；长期记忆由后台自动整理，不主动调用即时事实保存工具，不承诺没有成功写入的记忆。'
        '日常不要复述技术说明、工具名称或调用过程。工具可用列表：'
        + ','.join(t.get('name', t.get('function', {}).get('name', '')) for t in schemas)
        + f'。工具关闭时不得假称查过天气或网页；需要实时信息请使用可用工具。一次回复最多{MAX_TOOL_CALLS}次工具调用。TTS和休息提醒由网页设置及播放控件管理，不能通过聊天声称改变设置或创建后台通知。'
        + stickers.instruction(sticker_catalog)
        + (
            '文件处理在后台进行；提交成功时只需自然说一句先看看，不能声称已经读完或拿到结果，不复述任务标题或操作步骤。完成后的实际结果会直接回到聊天，聊天仍可继续。'
            '根据用户意图设置 read_document 的 scope：总结整份或全部附件使用 full；回答具体问题用 focused 并提供简短检索关键词 query；仅指定范围时用 range。'
            '只读附件：用 instruction 回答用户问题，在聊天中总结，不生成、修改文件或转换 PDF。扫描版 PDF 暂不支持。'
            '对聊天中主动发送的图片，直接使用本次会话模型识别。以工具实际返回为准。仅在切换外部视觉服务或达到工作量上限时询问。'
            if is_local
            else ''
        )
    )
