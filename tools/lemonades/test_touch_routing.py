"""Diagnostic parser must not turn registration/global messages into UI success."""
import unittest
from analyze_touch_routing import analyze


def fixture(integrated):
    log = 'BRIDGE TEST initial pid=6 service=256\nBRIDGE TEST restarted pid=25 service=257\n'
    for sender in ['100', '101']:
        events = [f'digitizer attached (sender {sender}) transport:Virtual builtIn: '+('YES' if integrated else 'NO')]
        if integrated:
            events += ['*** acquired main display digitizer (after 1s)', 'contact 1 presence: touching']
            if sender == '101': events += ['contact 1 presence: none']
        else:
            events += [f'ignoring digitizer event for display <main> from unsupported service: senderID: 0x{sender}']
        events += [f'digitizer detached (sender {sender})']
        if sender == '100' and integrated:
            events += [f'cancel -- digitizer did disappear: senderID: 0x{sender}; touchIdentifier: 1; touching; locked;']
        log += ''.join('BACKBOARD LOG | timestamp backboardd[7:8] [TouchEvents] '+event+'\n' for event in events)
    return log


class TouchRoutingTests(unittest.TestCase):
    def test_integrated_requires_contact_release_and_attributed_cancellation(self):
        log = fixture(True)
        report = analyze(log, True)
        self.assertTrue(report['routing_observed'])
        self.assertFalse(report['app_delivery_verified'])
        self.assertFalse(report['physical_input_verified'])
        for evidence in ['contact 1 presence: touching', 'contact 1 presence: none',
                         '*** acquired main display digitizer', 'digitizer detached (sender 101)',
                         'touchIdentifier: 1; touching;', 'BACKBOARD LOG | ']:
            self.assertFalse(analyze(log.replace(evidence, ''), True)['routing_observed'], evidence)
        self.assertFalse(analyze(log.replace('senderID: 0x100', 'senderID: 0x999'), True)['routing_observed'])
        self.assertFalse(analyze(log.replace('pid=25 service=257', 'pid=6 service=256'), True)['routing_observed'])
        overlapping = 'BACKBOARD LOG | backboardd[7:8] [TouchEvents] digitizer attached (sender 999)\n'
        self.assertFalse(analyze(overlapping+log, True)['routing_observed'])

    def test_external_requires_specific_rejection_and_cannot_prove_integrated_delivery(self):
        log = fixture(False)
        self.assertTrue(analyze(log, False)['routing_observed'])
        self.assertFalse(analyze(log, True)['routing_observed'])
        self.assertFalse(analyze(log.replace('senderID: 0x101', 'senderID: 0x999'), False)['routing_observed'])
        self.assertFalse(analyze(log.replace('builtIn: NO', 'builtIn: YES'), False)['routing_observed'])
        self.assertFalse(analyze(log.split('digitizer detached (sender 101)')[0], False)['routing_observed'])
