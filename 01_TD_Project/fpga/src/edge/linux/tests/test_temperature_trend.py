import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class IndependentTemperatureTrendTests(unittest.TestCase):
    def render(self, **changes):
        fields = dict(sequence='1', link='FCB1 + EDG1 ABI OK', panel_schema='industrial-v2',
                      panel_vibration_valid='0', frame_id='--', panel_source='WAIT', panel_sample_mode='2',
                      ui_configuration='unqualified', daily_rpm_valid='0', daily_rpm_value='--',
                      core_temperature_valid='1', core_temperature_source='DS18B20/S4b', core_temperature_c='27.5')
        fields.update(changes)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / 'state.txt'
            state.write_text(''.join(name + '=' + value + '\n' for name, value in fields.items()))
            audit = root / 'audit.txt'
            binary = Path(os.environ['CABINET_TEST_HMI'])
            subprocess.run([str(binary), str(state), str(root / 'preview.ppm')], check=True,
                           capture_output=True, env=dict(os.environ, CABINET_UI_AUDIT=str(audit)))
            return dict(line.split('=', 1) for line in audit.read_text().splitlines() if '=' in line)

    def test_temperature_without_rpm_or_feature_frame_is_plotted(self):
        fields = self.render()
        self.assertEqual(fields['temperature_trend_points'], '1')
        self.assertEqual(fields['rpm_trend_points'], '0')

    def test_rpm_without_temperature_is_plotted_independently(self):
        fields = self.render(daily_rpm_valid='1', daily_rpm_value='1234', core_temperature_valid='0')
        self.assertEqual(fields['temperature_trend_points'], '0')
        self.assertEqual(fields['rpm_trend_points'], '1')

    def test_invalid_temperature_cannot_populate_curve(self):
        fields = self.render(core_temperature_valid='0')
        self.assertEqual(fields['temperature_trend_points'], '0')

    def test_inlet_cannot_replace_core_temperature(self):
        fields = self.render(core_temperature_source='AHT20')
        self.assertEqual(fields['temperature_trend_points'], '0')

    def test_nan_temperature_is_not_plotted(self):
        fields = self.render(core_temperature_c='nan')
        self.assertEqual(fields['temperature_trend_points'], '0')

    def test_offline_clears_all_curves(self):
        fields = self.render(link='ERROR', daily_rpm_valid='1', daily_rpm_value='1234')
        self.assertEqual(fields['temperature_trend_points'], '0')
        self.assertEqual(fields['rpm_trend_points'], '0')

    def test_negative_rpm_does_not_suppress_valid_temperature(self):
        fields = self.render(daily_rpm_valid='1', daily_rpm_value='-1')
        self.assertEqual(fields['temperature_trend_points'], '1')
        self.assertEqual(fields['rpm_trend_points'], '0')
