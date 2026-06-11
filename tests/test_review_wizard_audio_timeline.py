import unittest

from scripts.review_wizard.audio_timeline import build_audio_timeline
from scripts.review_wizard.review_points import ReviewPoint


class AudioTimelineTests(unittest.TestCase):
    def test_build_audio_timeline_derives_waveform_and_active_region(self):
        points = [
            ReviewPoint(
                id="line-1",
                stage_id="alignment",
                level="line",
                text="Line",
                start_s=1.0,
                end_s=5.0,
            ),
            ReviewPoint(
                id="line-1:word-1",
                stage_id="alignment",
                level="word",
                text="Word",
                start_s=2.0,
                end_s=2.5,
            ),
        ]

        timeline = build_audio_timeline(points, duration_s=10.0, active_point_id="line-1:word-1")

        self.assertEqual(timeline["duration_s"], 10.0)
        self.assertEqual(len(timeline["waveform"]), 48)
        self.assertGreater(max(timeline["waveform"]), min(timeline["waveform"]))
        self.assertEqual(timeline["active_region"]["start_pct"], 20.0)
        self.assertEqual(timeline["active_region"]["width_pct"], 5.0)
        self.assertEqual(timeline["markers"][0]["label"], "LINE")
        self.assertEqual(timeline["markers"][1]["label"], "WORD")
        self.assertEqual([lane["id"] for lane in timeline["lanes"]], ["line", "word", "highlight", "issue"])
        self.assertEqual([marker["id"] for marker in timeline["lanes"][0]["markers"]], ["line-1"])
        self.assertEqual([marker["id"] for marker in timeline["lanes"][1]["markers"]], ["line-1:word-1"])
        self.assertEqual(timeline["lanes"][2]["markers"], [])
        self.assertEqual(timeline["lanes"][3]["markers"], [])
        self.assertEqual(timeline["lanes"][1]["markers"][0]["level"], "word")
        self.assertEqual(timeline["lanes"][1]["markers"][0]["status"], "open")
        self.assertEqual(timeline["lanes"][1]["markers"][0]["lane_id"], "word")
        self.assertEqual([tick["label"] for tick in timeline["ruler_ticks"]], ["0s", "2s", "4s", "6s", "8s", "10s"])
        self.assertEqual(timeline["playhead"]["left_pct"], 20.0)
        self.assertEqual(timeline["playhead"]["time_s"], 2.0)
        self.assertEqual(timeline["active_window"]["label"], "2.000s - 2.500s")

    def test_build_audio_timeline_groups_issues_into_issue_lane(self):
        points = [
            ReviewPoint(
                id="line-1",
                stage_id="alignment",
                level="line",
                text="Line",
                start_s=1.0,
                end_s=5.0,
            ),
            ReviewPoint(
                id="issue:timing-1",
                stage_id="quality",
                level="issue",
                text="Timing issue",
                start_s=3.0,
                end_s=3.4,
                status="open",
                severity="critical",
            ),
        ]

        timeline = build_audio_timeline(points, duration_s=10.0, active_point_id="issue:timing-1")

        self.assertEqual([lane["label"] for lane in timeline["lanes"]], ["LINE", "WORD", "HIGHLIGHT", "ISSUE"])
        self.assertEqual(timeline["lanes"][3]["markers"][0]["id"], "issue:timing-1")
        self.assertEqual(timeline["lanes"][3]["markers"][0]["severity"], "critical")
        self.assertEqual(timeline["active_region"]["start_pct"], 30.0)
        self.assertEqual(timeline["active_region"]["width_pct"], 4.0)

    def test_build_audio_timeline_adds_highlight_lane(self):
        highlight_segments = [
            {
                "id": "line-1:word-1:hv-1",
                "text": "sn",
                "start_s": 1.0,
                "end_s": 1.1,
                "role": "consonant_attack",
            },
            {
                "id": "line-1:word-1:hv-2",
                "text": "a",
                "start_s": 1.1,
                "end_s": 3.8,
                "role": "sustained_vowel",
            },
        ]

        timeline = build_audio_timeline(
            [],
            duration_s=5.0,
            active_point_id=None,
            highlight_segments=highlight_segments,
        )

        self.assertEqual([lane["id"] for lane in timeline["lanes"]], ["line", "word", "highlight", "issue"])
        self.assertEqual(timeline["lanes"][2]["markers"][1]["level"], "highlight")
        self.assertEqual(timeline["lanes"][2]["markers"][1]["role"], "sustained_vowel")
        self.assertEqual(timeline["lanes"][2]["markers"][1]["width_pct"], 54.0)

    def test_build_audio_timeline_clamps_markers_to_duration(self):
        points = [
            ReviewPoint(
                id="late",
                stage_id="alignment",
                level="word",
                text="Late",
                start_s=12.0,
                end_s=14.0,
            )
        ]

        timeline = build_audio_timeline(points, duration_s=10.0, active_point_id="late")

        self.assertEqual(timeline["active_region"]["start_pct"], 100.0)
        self.assertEqual(timeline["active_region"]["width_pct"], 0.0)
        self.assertEqual(timeline["markers"][0]["left_pct"], 100.0)
        self.assertEqual(timeline["playhead"]["left_pct"], 100.0)

    def test_build_audio_timeline_uses_zero_window_without_active_point(self):
        points = [
            ReviewPoint(
                id="line-1",
                stage_id="alignment",
                level="line",
                text="Line",
                start_s=1.0,
                end_s=5.0,
            )
        ]

        timeline = build_audio_timeline(points, duration_s=10.0, active_point_id="missing")

        self.assertEqual(timeline["active_region"], {"start_pct": 0.0, "width_pct": 0.0, "start_s": 0.0, "end_s": 0.0})
        self.assertEqual(timeline["playhead"], {"left_pct": 0.0, "time_s": 0.0})
        self.assertEqual(timeline["active_window"]["label"], "0.000s - 0.000s")


if __name__ == "__main__":
    unittest.main()
