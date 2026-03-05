from pathlib import Path
import unittest


class EncodingSanityTests(unittest.TestCase):
    # Typical UTF-8 mojibake fragments we already hit in runtime strings.
    BAD_MARKERS = (
        "вЂ",
        "рџ",
        "24С‡",
        "РџР",
        "РќР",
        "Р¤Р",
        "РљС",
        "РћС",
        "Р”Р",
        "Р Р",
        "СЌР",
    )

    TARGET_FILES = (
        Path("handlers/commands.py"),
        Path("services/messages.py"),
        Path("app/dashboard.html"),
    )

    def test_no_known_mojibake_markers_in_ui_text(self) -> None:
        for file_path in self.TARGET_FILES:
            self.assertTrue(file_path.exists(), f"Missing target file: {file_path}")
            data = file_path.read_text(encoding="utf-8")
            for marker in self.BAD_MARKERS:
                with self.subTest(file=str(file_path), marker=marker):
                    self.assertNotIn(marker, data)


if __name__ == "__main__":
    unittest.main()
