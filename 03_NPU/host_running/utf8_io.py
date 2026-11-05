"""Stable Unicode logs and CLI JSON regardless of the LaunchAgent locale."""
import sys

def configure_stdio():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
