#!/usr/bin/env python3
"""Inspect production diagnostic status; production feature injection is disabled.

Synthetic demonstrations must use an isolated TEST replay service and dataset.
This utility never writes sensor values, injection markers, configuration or PWM.
"""
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', default='status',
                        choices=('status', 'normal', 'imbalance', 'stall', 'clog', 'overheat', 'auto', 'clear'))
    args = parser.parse_args()
    if args.mode != 'status':
        parser.error('R46 production feature injection is disabled; use an isolated, explicit TEST replay workflow')
    print('生产数据注入已禁用；以下仅为当前状态，不代表模型或传感器验收。')
    path = Path('/run/cabinet-live/state.txt')
    if not path.is_file():
        print('当前运行状态不可读。')
        return 1
    keys = ('link=', 'frame_state=', 'frame_calibrated=', 'quality_reasons=',
            'panel_model_valid=', 'panel_model_state=', 'capture_training_ready=')
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith(keys):
            print(line)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
