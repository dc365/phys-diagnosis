from __future__ import annotations

import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
from weather_diag.data.reader import inspect_netcdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    args = parser.parse_args()
    print(json.dumps(inspect_netcdf(args.path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
