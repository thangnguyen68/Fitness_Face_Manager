import unittest
from datetime import date, timedelta
from unittest.mock import patch

from main import _recent_recognitions, decide, recognized_decision


def member(end_offset: int, status: str = 'active') -> dict:
    today = date.today()
    return {
        'id': 'test-member',
        'full_name': 'Hội viên thử nghiệm',
        'status': status,
        'memberships': [{
            'plan_id': 'test-plan',
            'start_date': (today - timedelta(days=30)).isoformat(),
            'end_date': (today + timedelta(days=end_offset)).isoformat(),
        }],
    }


class AccessDecisionTests(unittest.TestCase):
    def setUp(self):
        self.record = patch('main.access_log', side_effect=lambda person, direction, decision, reason=None, score=None, **kwargs: {'decision': decision, 'reason_code': reason})
        self.log = self.record.start()
        self.addCleanup(self.record.stop)
        _recent_recognitions.clear()
        self.addCleanup(_recent_recognitions.clear)

    def test_repeated_entry_is_allowed(self):
        person = member(10)
        self.assertEqual(decide(person, 'IN')['decision'], 'ALLOW')
        self.assertEqual(decide(person, 'IN')['decision'], 'ALLOW')

    def test_unknown_face_is_not_allowed(self):
        self.assertEqual(decide(None, 'IN')['reason_code'], 'UNKNOWN_FACE')

    def test_expired_membership_is_denied_in_both_directions(self):
        for direction in ('IN', 'OUT'):
            with self.subTest(direction=direction):
                self.assertEqual(decide(member(-1), direction)['reason_code'], 'MEMBERSHIP_EXPIRED')

    def test_member_status_does_not_add_another_denial_reason(self):
        self.assertEqual(decide(member(10, 'suspended'), 'IN')['decision'], 'ALLOW')

    def test_one_log_per_encounter_until_member_returns(self):
        person = member(10)
        first = recognized_decision(person, 'IN', encounter_id='camera:1')
        repeated = recognized_decision(person, 'IN', encounter_id='camera:1')
        self.assertIs(first, repeated)
        self.assertEqual(self.log.call_count, 1)
        recognized_decision(person, 'IN', encounter_id='camera:2')
        self.assertEqual(self.log.call_count, 2)


if __name__ == '__main__':
    unittest.main()
