"""Build the dashboard's Chinese font subset with explicit local tool inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True)
    parser.add_argument('--font', type=Path, required=True)
    parser.add_argument('--converter', type=Path, required=True)
    parser.add_argument('--font-python', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if args.font_python:
        sys.path.insert(0, str(args.font_python))
    from fontTools import subset
    from fontTools.ttLib import TTFont
    text = '\n'.join((root / name).read_text(encoding='utf-8') for name in
                     ('dashboard.c', 'capture_view.h', 'daily.py', 'instrument.py', 'presentation.py'))
    symbols = ''.join(sorted({character for character in text if ord(character) >= 128}))
    output = root / 'fonts'
    compact = output / 'ui_subset.otf'
    font = TTFont(str(args.font))
    options = subset.Options()
    options.layout_features = []
    options.hinting = False
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=set(range(32, 127)) | {ord(character) for character in symbols})
    subsetter.subset(font)
    font.save(str(compact))
    for size in (16, 18, 20, 28):
        subprocess.run([args.node, str(args.converter), '--size', str(size), '--bpp', '4',
                        '--format', 'lvgl', '--font', str(compact), '--range', '0x20-0x7e',
                        '--symbols', symbols, '--no-compress', '--no-kerning', '--lv-include', 'lvgl.h',
                        '--lv-font-name', 'ui_zh_%d' % size, '-o', str(output / ('ui_zh_%d.c' % size))], check=True)
    compact.unlink()
    report = dict(font_source=args.font.name, source_sha256=hashlib.sha256(args.font.read_bytes()).hexdigest(),
                  converter_version='1.5.3', sizes=[16, 18, 20, 28], glyphs=symbols,
                  non_ascii_glyphs=len(symbols))
    (output / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Generated %d Chinese/symbol glyphs in four sizes' % len(symbols))


if __name__ == '__main__':
    main()
