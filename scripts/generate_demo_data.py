from __future__ import annotations

import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from weather_diag.data.synthetic import create_demo_ecmwf_netcdf


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/raw/ecmwf_demo.nc")
    args = parser.parse_args()
    path = create_demo_ecmwf_netcdf(args.output)
    print(path)


if __name__ == "__main__":
    main()
