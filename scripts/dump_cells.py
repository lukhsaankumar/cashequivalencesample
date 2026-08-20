"""Dump cell values+formulas for target sheets/ranges to a text file for analysis."""
import sys
from pathlib import Path
import openpyxl

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source_material"


def dump_range(ws_f, ws_v, cell_range, out):
    out.write(f"\n--- {ws_f.title} {cell_range} ---\n")
    for row_f, row_v in zip(ws_f[cell_range], ws_v[cell_range]):
        for cf, cv in zip(row_f, row_v):
            if cf.value is not None or cv.value is not None:
                out.write(f"{cf.coordinate}: formula={cf.value!r} value={cv.value!r}\n")


def main():
    path = SRC / sys.argv[1]
    out_path = Path(sys.argv[2])
    targets = eval(sys.argv[3])  # list of (sheet, range)
    wb_f = openpyxl.load_workbook(path, data_only=False)
    wb_v = openpyxl.load_workbook(path, data_only=True)
    with open(out_path, "w", encoding="utf-8") as out:
        for sheet, rng in targets:
            ws_f = wb_f[sheet]
            ws_v = wb_v[sheet]
            dump_range(ws_f, ws_v, rng, out)
    print("wrote", out_path)


if __name__ == "__main__":
    main()
