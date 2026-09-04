import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

from app.enhanced import curve_pwm, validate_enhanced
from app.fancontrol import parse_pairs


class CoreTests(unittest.TestCase):
    def test_parse_pairs(self):
        self.assertEqual(
            parse_pairs("hwmon0/pwm1=40 hwmon1/pwm2=50"),
            {"hwmon0/pwm1": "40", "hwmon1/pwm2": "50"},
        )

    def test_curve_interpolation(self):
        points = [
            {"temp": 40, "pwm": 30},
            {"temp": 60, "pwm": 70},
            {"temp": 80, "pwm": 100},
        ]
        self.assertEqual(curve_pwm(40, points), 30)
        self.assertEqual(curve_pwm(50, points), 50)
        self.assertEqual(curve_pwm(90, points), 100)

    def test_curve_validation_rejects_decreasing_pwm(self):
        with self.assertRaises(ValueError):
            validate_enhanced({
                "enabled": False,
                "interval": 2,
                "channels": [{
                    "pwm": "/sys/class/hwmon/hwmon0/pwm1",
                    "sources": [{"kind": "nvidia", "gpu_index": 0}],
                    "points": [{"temp": 40, "pwm": 70}, {"temp": 60, "pwm": 50}],
                    "hysteresis": 3,
                    "emergency_temp": 82,
                }],
            })

    def test_host_temp_source_failsafe_is_millidegree(self):
        helper = ROOT / "scripts" / "host-temp-source.py"
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "source.json"
            config.write_text(json.dumps({"sources": [], "failsafe_temp": 97.5}), encoding="utf-8")
            p = subprocess.run(
                [sys.executable, str(helper), str(config)],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(p.stdout.strip(), "97500")


if __name__ == "__main__":
    unittest.main()
