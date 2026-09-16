"""
Unit tests for protocol.py – Zero-I/O Binary Protocol Engine
Uses Python's built-in unittest module.
"""

import unittest
import protocol as p


class TestCommandEncoders(unittest.TestCase):
    def test_query_status(self):
        frame = p.encode_query_status(seq=1)
        self.assertEqual(frame, bytes.fromhex("fedcbac402000501ffffffffef"))

    def test_anc_mode(self):
        frame = p.encode_anc_mode(mode=1, seq=42)
        self.assertTrue(frame.startswith(b'\xfe\xdc\xba\xc4\x08\x00'))
        self.assertEqual(frame[7], 42)
        self.assertEqual(frame[8:11], b'\x02\x04\x01')
        self.assertEqual(frame[-1], 0xEF)

    def test_anc_depth(self):
        frame = p.encode_anc_depth(depth=2, seq=5)
        self.assertTrue(frame.startswith(b'\xfe\xdc\xba\xc4\xf2\x00'))
        self.assertEqual(frame[8:13], b'\x04\x00\x0b\x01\x02')
        self.assertEqual(frame[-1], 0xEF)

    def test_dual_connection(self):
        frame_enable = p.encode_dual_connection(True, seq=10)
        self.assertTrue(frame_enable.startswith(b'\xfe\xdc\xba\xc4\xf2\x00'))
        self.assertEqual(frame_enable[8:12], b'\x03\x00\x04\x01')

        frame_disable = p.encode_dual_connection(False, seq=11)
        self.assertEqual(frame_disable[8:12], b'\x03\x00\x04\x00')

    def test_le_mode(self):
        frames, next_seq = p.encode_le_mode(enabled=True, seq_start=20)
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0][8:12], b'\x03\x00\x28\x00')
        self.assertEqual(frames[1][8:12], b'\x03\x00\x07\x00')
        self.assertEqual(next_seq, 22)


class TestBatteryParser(unittest.TestCase):
    def test_battery_tag_normal(self):
        data = bytes.fromhex("00000407d55a6400")
        bat = p.parse_battery_tag(data)
        self.assertIsNotNone(bat)
        self.assertEqual(bat.left, 85)
        self.assertTrue(bat.charging_left)
        self.assertEqual(bat.right, 90)
        self.assertFalse(bat.charging_right)
        self.assertEqual(bat.case, 100)
        self.assertFalse(bat.charging_case)

    def test_battery_tag_disconnected(self):
        data = bytes.fromhex("0407ffffff")
        bat = p.parse_battery_tag(data)
        self.assertIsNotNone(bat)
        self.assertEqual(bat.left, -1)
        self.assertFalse(bat.charging_left)


class TestStreamParser(unittest.TestCase):
    def test_anc_notification(self):
        frame = bytes.fromhex("fedcbac708000401020402ef")
        events, remaining = p.parse_stream(frame)
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], p.AncModeEvent)
        self.assertEqual(events[0].mode, 2)

    def test_dual_connection_notification(self):
        frame = bytes.fromhex("fedcbac7f200050203000401ef")
        events, remaining = p.parse_stream(frame)
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], p.DualConnectionEvent)
        self.assertTrue(events[0].enabled)

    def test_stream_fragmentation(self):
        part1 = bytes.fromhex("fedcbac7f2000502")
        part2 = bytes.fromhex("03000401ef")

        events1, rem1 = p.parse_stream(part1)
        self.assertEqual(len(events1), 0)
        self.assertEqual(rem1, part1)

        events2, rem2 = p.parse_stream(rem1 + part2)
        self.assertEqual(len(events2), 1)
        self.assertIsInstance(events2[0], p.DualConnectionEvent)
        self.assertTrue(events2[0].enabled)

    def test_stream_noise_recovery(self):
        noisy_stream = b"GARBAGE_NOISE\xfe\xdc\xba\xc7\x08\x00\x04\x01\x02\x04\x01\xef"
        events, _ = p.parse_stream(noisy_stream)
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], p.AncModeEvent)
        self.assertEqual(events[0].mode, 1)

    def test_multi_frame_burst(self):
        frame1 = bytes.fromhex("fedcbac708000401020400ef")
        frame2 = bytes.fromhex("fedcbac7f200050203000401ef")
        burst = frame1 + frame2
        events, _ = p.parse_stream(burst)
        self.assertEqual(len(events), 2)
        self.assertIsInstance(events[0], p.AncModeEvent)
        self.assertEqual(events[0].mode, 0)
        self.assertIsInstance(events[1], p.DualConnectionEvent)
        self.assertTrue(events[1].enabled)

    def test_f400_notifications(self):
        # ANC Depth Smart
        frame_smart = bytes.fromhex("fedcbac7f400060804000b0000ef")
        ev_smart, _ = p.parse_stream(frame_smart)
        self.assertEqual(len(ev_smart), 1)
        self.assertIsInstance(ev_smart[0], p.AncDepthEvent)
        self.assertEqual(ev_smart[0].depth, 0)

        # Commute mode Train (mode 1)
        frame_commute = bytes.fromhex("fedcbac7f40006160400670102ef")
        ev_commute, _ = p.parse_stream(frame_commute)
        self.assertEqual(len(ev_commute), 1)
        self.assertIsInstance(ev_commute[0], p.CommuteModeEvent)
        self.assertEqual(ev_commute[0].mode, 1)

        # Transparency Ambience (mode 1)
        frame_trans = bytes.fromhex("fedcbac7f400060204000b0201ef")
        ev_trans, _ = p.parse_stream(frame_trans)
        self.assertEqual(len(ev_trans), 1)
        self.assertIsInstance(ev_trans[0], p.TransparencySubmodeEvent)
        self.assertEqual(ev_trans[0].submode, 1)

        # In-ear detection enabled
        frame_inear = bytes.fromhex("fedcbac7f400051203002501ef")
        ev_inear, _ = p.parse_stream(frame_inear)
        self.assertEqual(len(ev_inear), 1)
        self.assertIsInstance(ev_inear[0], p.InEarDetectionEvent)
        self.assertTrue(ev_inear[0].enabled)

    def test_0e00_battery_notification(self):
        # Left: 65% charging, Right: 65% discharging, Case: 100% discharging
        frame_batt = bytes.fromhex("fedcbac70e0006060400c14164ef")
        ev_batt, _ = p.parse_stream(frame_batt)
        self.assertEqual(len(ev_batt), 1)
        self.assertIsInstance(ev_batt[0], p.BatteryEvent)
        self.assertEqual(ev_batt[0].left, 65)
        self.assertTrue(ev_batt[0].charging_left)
        self.assertEqual(ev_batt[0].right, 65)
        self.assertFalse(ev_batt[0].charging_right)
        self.assertEqual(ev_batt[0].case, 100)
        self.assertFalse(ev_batt[0].charging_case)


if __name__ == '__main__':
    unittest.main()

