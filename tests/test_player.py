import unittest

from voyager.player import format_time, is_video_file


class PlayerHelpersTests(unittest.TestCase):
    def test_video_detection_is_case_insensitive(self):
        self.assertTrue(is_video_file("lesson.MOV"))
        self.assertTrue(is_video_file("lesson.mp4"))
        self.assertFalse(is_video_file("chord.png"))
        self.assertFalse(is_video_file("take.wav"))

    def test_format_time(self):
        self.assertEqual(format_time(0), "0:00")
        self.assertEqual(format_time(65_500), "1:05")
        self.assertEqual(format_time(-5), "0:00")


if __name__ == "__main__":
    unittest.main()
