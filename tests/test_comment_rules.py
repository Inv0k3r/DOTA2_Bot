import unittest
from unittest.mock import patch

import comment_rules


class CommentRulesTest(unittest.TestCase):
    def test_parse_short_rule(self):
        conditions, probability, text = comment_rules.parse_add_rule(
            '死亡>=10 KDA<1 60% 泉水到战场这条路算是让你跑明白了。'
        )
        self.assertEqual(probability, 60)
        self.assertEqual(text, '泉水到战场这条路算是让你跑明白了。')
        self.assertEqual(conditions[0], {'field': 'deaths', 'op': '>=', 'value': 10.0})
        self.assertEqual(conditions[1], {'field': 'kda', 'op': '<', 'value': 1.0})

    def test_parse_win_and_percentage(self):
        conditions, probability, _ = comment_rules.parse_add_rule(
            '胜负=负 伤害占比>=40% 100% 尽力局。'
        )
        self.assertEqual(conditions[0]['value'], False)
        self.assertEqual(conditions[1]['value'], 40.0)
        self.assertEqual(probability, 100)

    def test_percentage_condition_is_not_trigger_probability(self):
        conditions, probability, text = comment_rules.parse_add_rule(
            '胜负=负 伤害占比>=40% 75% 你一个人把活全干了。'
        )
        self.assertEqual(conditions[1], {
            'field': 'damage_share', 'op': '>=', 'value': 40.0,
        })
        self.assertEqual(probability, 75)
        self.assertEqual(text, '你一个人把活全干了。')

    def test_full_width_and_probability_label(self):
        conditions, probability, text = comment_rules.parse_add_rule(
            '死亡 ＞＝ 10　概率＝60％：泉水通勤大师。'
        )
        self.assertEqual(conditions[0], {'field': 'deaths', 'op': '>=', 'value': 10.0})
        self.assertEqual(probability, 60)
        self.assertEqual(text, '泉水通勤大师。')

    @patch('comment_rules.get_comment_vote_summary', return_value={})
    @patch('comment_rules.get_comment_rules')
    def test_custom_comment_is_deterministic(self, get_rules, _votes):
        get_rules.return_value = [{
            'id': 7,
            'conditions': [{'field': 'deaths', 'op': '>=', 'value': 10}],
            'probability': 100,
            'text': '自定义毒舌',
        }]
        stats = {'deaths': 12}
        first = comment_rules.choose_custom_comment(1, 123, 42, stats)
        second = comment_rules.choose_custom_comment(1, 123, 42, stats)
        self.assertEqual(first, '自定义毒舌')
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
