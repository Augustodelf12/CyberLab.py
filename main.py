#!/usr/bin/env python3
"""Shim para rodar o CyberLab direto da fonte (dev):  python main.py"""
from lab.cli import main

if __name__ == "__main__":
    raise SystemExit(main())