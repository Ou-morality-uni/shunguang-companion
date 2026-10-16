"""Route personal context separately from lore; reject unrelated vector neighbours."""

import re
from functools import lru_cache

PERSONAL = re.compile(
    r'我(?:是哪里人|的(?:家乡|籍贯|名字|喜好|住址)|来自哪里|住哪)|记得我|记住|忘掉|忘记|上[个次回]|昨天.*聊|聊天框|聊过'
)
REALTIME = re.compile(r'天气|气温|下雨|新闻|搜索|查询网页|查一下')
IDENTITY = re.compile(r'^(?:你是谁|你叫什么(?:名字)?|你来自哪里|你是哪里人)[？?。！!\s]*$')


@lru_cache(maxsize=1)
def _entities(stamp):
    from .rag import load_corpus

    chunks, _ = load_corpus()
    names = {'叶瞬光', '绝区零', '云岿山', '邦布', '六分街', '新艾利都', '空洞', '以太'}
    for chunk in chunks:
        heading = chunk.get('title', '').split('/')[-1]
        heading = re.sub(r'（.*?）|\(.*?\)|\.md|官方核实|姓名与阵营', '', heading)
        for part in re.findall(r'[\u4e00-\u9fff]{2,12}', heading):
            if part not in {'绝区零', '官方资料', '角色设定', '官方核实'}:
                names.add(part)
    return frozenset(names)


def entities():
    from .rag import RESOURCE_DIR

    files = [
        RESOURCE_DIR / 'character/manifest.json',
        RESOURCE_DIR / 'world/manifest.json',
        RESOURCE_DIR / 'verified/knowledge-verified.json',
    ]
    stamp = tuple(path.stat().st_mtime_ns if path.exists() else 0 for path in files)
    return _entities(stamp)


def route(query):
    if IDENTITY.fullmatch(query.strip()):
        return {'domain': 'identity', 'search': False, 'query': query}
    if (
        PERSONAL.search(query)
        and re.search(r'再(?:讲|说|介绍)|还想了解|接着讲', query)
        and any(word in query for word in entities())
    ):
        return {'domain': 'memory_knowledge', 'search': True, 'query': query}
    if PERSONAL.search(query):
        return {'domain': 'memory', 'search': False, 'query': query}
    if REALTIME.search(query) and '游戏' not in query and '绝区零' not in query:
        return {'domain': 'tools', 'search': False, 'query': query}
    resolved = query
    if re.search(r'你.{0,8}(阵营|师父|武器|经历|门派|招式|技能)', query):
        resolved = '叶瞬光 ' + query
    known = [word for word in entities() if word in resolved]
    explicit = bool(re.search(r'绝区零|游戏(?:设定|剧情|角色|世界)', query))
    return {
        'domain': 'knowledge' if known or explicit else 'conversation',
        'search': bool(known or explicit),
        'query': resolved,
    }


def relevant_sources(query, sources, limit=4):
    mentioned = {word for word in entities() if word in query and word != '绝区零'}
    if len(mentioned) > 1:
        mentioned.discard('叶瞬光')
    title_matches = [source for source in sources if any(word in str(source.get('title', '')) for word in mentioned)]
    if title_matches:
        sources = title_matches
    topic_terms = {
        '阵营': ('阵营', '门派', '云岿山', '所属'),
        '武器': ('武器', '剑', '刀', '兵器'),
        '哥哥': ('哥哥', '兄长', '叶释渊'),
        '性格': ('性格', '温柔', '亲切', '坚韧'),
    }
    result = []
    seen = set()
    for source in sources:
        text = str(source.get('text', ''))
        heading = str(source.get('title', ''))
        if mentioned and not any(word in heading or word in text for word in mentioned):
            continue
        if any(
            topic in query and not any(term in heading + text for term in terms) for topic, terms in topic_terms.items()
        ):
            continue
        if not mentioned:
            terms = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', query)
            grams = {term[i : i + 2] for term in terms for i in range(len(term) - 1)}
            if not grams or sum(term in heading + text for term in grams) / len(grams) < 0.3:
                continue
        if text in seen:
            continue
        seen.add(text)
        result.append(source)
        if len(result) >= limit:
            break
    return result


def cited_sources(text, context):
    numbers = {int(n) for n in re.findall(r'\[(\d+)\]', text)}
    return [{**source, 'usage': 'cited'} for source in context if source.get('number') in numbers]
