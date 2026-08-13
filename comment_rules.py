#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Parse, format and deterministically evaluate group-defined comments."""
import hashlib
import re
import unicodedata

from DBOper import get_comment_rules, get_comment_vote_summary


FIELDS = {
    '击杀': 'kills', '死亡': 'deaths', '助攻': 'assists',
    'KDA': 'kda', 'GPM': 'gpm', 'XPM': 'xpm',
    '补刀': 'last_hits', '伤害': 'damage',
    '伤害占比': 'damage_share', '参战率': 'participation',
    '死亡占比': 'death_share', '胜负': 'won',
}
DISPLAY_FIELDS = {value: key for key, value in FIELDS.items()}
CONDITION_RE = re.compile(
    r'^(击杀|死亡|助攻|KDA|GPM|XPM|补刀|伤害|伤害占比|参战率|死亡占比|胜负)'
    r'(>=|<=|=|>|<)(.+)$', re.IGNORECASE
)


def parse_add_rule(arguments):
    # QQ users often enter full-width punctuation. NFKC also normalizes full-width
    # spaces/operators while leaving Chinese text intact.
    normalized = unicodedata.normalize('NFKC', arguments).strip()
    probability_matches = list(re.finditer(
        r'(?<!\S)(?:概率\s*=?\s*)?(\d{1,3})\s*%(?=\s|[|:：]|$)',
        normalized,
    ))
    if not probability_matches:
        raise ValueError('格式：加锐评 死亡>=10 60% 文案（概率也可写 概率=60%）')
    # A percentage condition such as 伤害占比>=40% is not an independent token
    # and therefore cannot be mistaken for the trigger probability.
    probability_match = probability_matches[-1]
    probability = int(probability_match.group(1))
    if not 1 <= probability <= 100:
        raise ValueError('概率必须是 1% 到 100%')
    condition_text = normalized[:probability_match.start()].strip()
    text = normalized[probability_match.end():].lstrip(' |:：').strip()
    if not text:
        raise ValueError('锐评文案不能为空')
    if len(text) > 100:
        raise ValueError('锐评文案最多 100 个字符')
    if '[CQ:' in text or 'http://' in text.lower() or 'https://' in text.lower() or '@全体成员' in text:
        raise ValueError('文案不能包含链接、CQ 码或 @全体成员')

    condition_text = re.sub(r'\s*(>=|<=|=|>|<)\s*', r'\1', condition_text)
    tokens = condition_text.replace('，', ' ').replace(',', ' ').split()
    if not 1 <= len(tokens) <= 5:
        raise ValueError('请设置 1 到 5 个条件，条件之间用空格分开')
    conditions = []
    for token in tokens:
        match = CONDITION_RE.fullmatch(token)
        if not match:
            raise ValueError('无法识别条件：{}'.format(token))
        field_label, operator, raw_value = match.groups()
        field = FIELDS.get(field_label.upper(), FIELDS.get(field_label))
        if field == 'won':
            if operator != '=' or raw_value not in ('胜', '负'):
                raise ValueError('胜负条件只能写成 胜负=胜 或 胜负=负')
            value = raw_value == '胜'
        else:
            raw_value = raw_value.rstrip('%')
            try:
                value = float(raw_value)
            except ValueError as exc:
                raise ValueError('{} 的数值不合法'.format(field_label)) from exc
        conditions.append({'field': field, 'op': operator, 'value': value})
    return conditions, probability, text


def format_condition(condition):
    value = condition['value']
    if condition['field'] == 'won':
        value = '胜' if value else '负'
    elif isinstance(value, float) and value.is_integer():
        value = int(value)
    suffix = '%' if condition['field'] in ('damage_share', 'participation', 'death_share') else ''
    return '{}{}{}{}'.format(
        DISPLAY_FIELDS[condition['field']], condition['op'], value, suffix
    )


def format_rule(rule, include_text=False):
    conditions = ' '.join(format_condition(item) for item in rule['conditions'])
    line = '#{} [{}] {} {}%'.format(
        rule['id'], '开' if rule['enabled'] else '停', conditions, rule['probability']
    )
    return '{}\n{}'.format(line, rule['text']) if include_text else line


def _matches(condition, stats):
    actual = stats.get(condition['field'])
    expected = condition['value']
    operators = {
        '>=': lambda: actual >= expected, '<=': lambda: actual <= expected,
        '>': lambda: actual > expected, '<': lambda: actual < expected,
        '=': lambda: actual == expected,
    }
    return actual is not None and operators[condition['op']]()


def choose_custom_comment(group_id, match_id, account_id, stats):
    votes = get_comment_vote_summary(group_id)
    # 群体反馈只做温和修正，避免少量投票把规则推到极端。
    probability_adjustment = max(
        -20, min(20, (votes.get('light', 0) - votes.get('heavy', 0)) * 2)
    )
    for rule in get_comment_rules(group_id, include_disabled=False):
        if not all(_matches(condition, stats) for condition in rule['conditions']):
            continue
        seed = '{}:{}:{}'.format(match_id, account_id, rule['id']).encode('utf-8')
        roll = int.from_bytes(hashlib.sha256(seed).digest()[:8], 'big') % 100 + 1
        effective_probability = max(
            1, min(100, rule['probability'] + probability_adjustment)
        )
        if roll <= effective_probability:
            return rule['text']
    return None
