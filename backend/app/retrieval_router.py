"""Route personal context separately from lore; reject unrelated vector neighbours."""

import re
from functools import lru_cache

PERSONAL = re.compile(
    r'我(?:是哪里人|的(?:家乡|籍贯|名字|喜好|住址)|来自哪里|住哪)|记得我|记住|忘掉|忘记|上[个次回]|昨天.*聊|聊天框|聊过'
)
REALTIME = re.compile(r'天气|气温|下雨|新闻|搜索|查询网页|查一下')
IDENTITY = re.compile(r'^(?:你是谁|你叫什么(?:名字)?|你来自哪里|你是哪里人)[？?。！!\s]*$')
CHARACTER_ENTITIES = frozenset(
    {
        '叶瞬光',
        '绝区零',
        '云岿山',
        '邦布',
        '六分街',
        '新艾利都',
        '空洞',
        '以太',
        '青溟剑',
        '仪玄',
        '叶释渊',
        '橘福福',
        '潘引壶',
        '般岳',
        '仪绛',
        '芽芽',
        '剑主',
        '桂花糕',
        '桂花糖',
        '明心境',
        '虚狩',
        '青溟司命',
        '澄辉坪',
        '渺渺微光',
        '赤焰宁光',
    }
)
# Question words alone (e.g. “你怎么了”) are ordinary conversation, not lore.
CHARACTER_QUESTION = re.compile(
    r'(?:你|小光).{0,12}(?:阵营|师父|师傅|师兄|师姐|哥哥|父母|家人|武器|经历|经过|身世|过去|以前|小时候|'
    r'门派|招式|技能|生日|身高|喜欢吃|写日记|五感|失忆|记忆|忘事|忘记|秘境|年表)|'
    r'拜师|师门|身世|拜入|(?:当年|哪年|几岁|小时候|师父|师傅).{0,12}(?:入门|进门|上山)'
)


@lru_cache(maxsize=1)
def _entities(stamp):
    from .rag import load_corpus

    chunks, _ = load_corpus()
    names = set(CHARACTER_ENTITIES)
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
    character_question = CHARACTER_QUESTION.search(query)
    # A character forgetting her past is different from a user's memory request.
    personal = PERSONAL.search(query) and not (
        character_question
        and re.search(r'你.{0,8}(?:会|会不会|为什么|为何|是不是|已经)?忘记', query)
        and not re.search(r'记得我|记住|忘记.{0,4}我|聊过|聊天框', query)
    )
    if personal and re.search(r'再(?:讲|说|介绍)|还想了解|接着讲', query) and any(word in query for word in entities()):
        return {'domain': 'memory_knowledge', 'search': True, 'query': query}
    if personal:
        return {'domain': 'memory', 'search': False, 'query': query}
    if REALTIME.search(query) and '游戏' not in query and '绝区零' not in query:
        return {'domain': 'tools', 'search': False, 'query': query}
    resolved = query
    if character_question and '叶瞬光' not in query:
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
        '拜师': ('拜师', '拜入', '拜仪玄', '仪玄为师', '入门', '送往云岿山', '带上云岿山'),
        '师父': ('师父', '师傅', '仪玄'),
        '师傅': ('师父', '师傅', '仪玄'),
        '身世': ('身世', '父母', '童年', '般岳', '旧都陷落'),
        '秘境': ('秘境', '古阵', '矿区旧址', '幻境'),
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
