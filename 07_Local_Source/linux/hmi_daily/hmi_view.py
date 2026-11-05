"""Switch only the local display page; never touches MMIO or actuator control."""
import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('page', choices=['overview', 'features', 'alarms'])
    args = parser.parse_args()
    directory = Path('/run/cabinet-live')
    directory.mkdir(exist_ok=True)
    temporary = directory / 'ui_view.new'
    temporary.write_text(args.page + '\n')
    os.replace(str(temporary), str(directory / 'ui_view'))


if __name__ == '__main__':
    main()
