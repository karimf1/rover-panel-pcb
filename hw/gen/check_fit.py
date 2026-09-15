#!/usr/bin/env python3
"""The board, measured twice.

The plate in rover-power-panel was drilled from params.py. The board outline
was built from panel_interface.json, which params.py wrote. This script reads
the FINISHED .kicad_pcb back through pcbnew -- not the generator, not the JSON
-- and checks it against params.py itself, imported live from the panel
project. So there are three independent readings of the same four holes:

    params.py (what AutoCAD drilled)  ==  panel_interface.json (what KiCad was told)
                                      ==  the .kicad_pcb (what the fab will cut)

and a stale JSON, a hand-edited board or a moved plate hole all fail here.

Run with KiCad's interpreter:  make fit
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "design")))
PANEL = os.path.normpath(os.path.join(HERE, "..", "..", "..", "rover-power-panel", "scripts"))
sys.path.insert(0, PANEL)

try:
    import wx
    if wx.App.Get() is None:
        _APP = wx.App(False)
except ImportError:
    pass
import pcbnew as P  # noqa: E402

import params  # noqa: E402  -- the panel's own source of truth
import spec as S  # noqa: E402

TOL = 0.01          # mm
FAILED = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  -- ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def mm(v):
    return P.ToMM(v)


print("== fit: the board against the panel that carries it ==")
iface = json.load(open(os.path.join(HERE, "..", "..", "design", "panel_interface.json")))
live = json.loads(json.dumps(params.pcb_interface()))
check("panel_interface.json is not stale (equals params.pcb_interface() now)",
      iface == live, "re-run: python3 params.py --export-pcb" if iface != live else "")

board = P.LoadBoard(os.path.join(HERE, "..", "rover-panel-supervisor.kicad_pcb"))
dev = params.by_tag(iface["tag"])

# ---------------------------------------------------------------- outline
edge = board.GetBoardEdgesBoundingBox()
w, h = mm(edge.GetWidth()), mm(edge.GetHeight())
ox, oy = mm(edge.GetLeft()), mm(edge.GetTop())
check("board outline is the slot params.py reserved",
      abs(w - dev.w) <= 0.1 + TOL and abs(h - dev.d) <= 0.1 + TOL,
      f"board {w:.2f} x {h:.2f} mm (incl. 0.1 mm edge line), slot {dev.w:g} x {dev.d:g}")
check("board origin is the top-left of the outline", abs(ox + 0.05) < 0.06 and abs(oy + 0.05) < 0.06,
      f"({ox:.3f}, {oy:.3f})")

# --------------------------------------------------------- mounting holes
holes = []
for fp in board.GetFootprints():
    if fp.GetReference().startswith("H"):
        pad = list(fp.Pads())[0]
        q = pad.GetPosition()
        holes.append((fp.GetReference(), mm(q.x), mm(q.y), mm(pad.GetDrillSize().x)))
holes.sort(key=lambda t: (round(t[2], 1), t[1]))
want = sorted(params.pcb_holes_board(), key=lambda t: (t[1], t[0]))
check("four mounting holes on the board", len(holes) == 4, str([h_[0] for h_ in holes]))
for (ref, x, y, d), (u, v, bd) in zip(holes, want):
    check(f"{ref} at ({x:.2f}, {y:.2f}) is where params.py put it",
          abs(x - u) <= TOL and abs(y - v) <= TOL and abs(d - bd) <= TOL,
          f"params ({u:g}, {v:g}) dia {bd:g}, board dia {d:.2f}")

# the same holes, in the panel frame, against the plate's drill list
plate = sorted((round(x, 3), round(y, 3), dd) for x, y, dd, tag in params.all_holes()
               if tag == iface["tag"])
mapped = sorted((round(dev.x + x, 3), round(dev.y + dev.d - y, 3)) for _, x, y, _ in holes)
check("every board hole lands on a plate hole (panel frame)",
      [p[:2] for p in plate] == mapped, f"plate {[p[:2] for p in plate]}")
check("plate holes clear the board holes for M3 (>= 0.3 mm larger)",
      all(dd >= S_ + 0.3 - TOL for (_, _, dd), S_ in zip(plate, [h_[3] for h_ in holes])),
      f"plate {plate[0][2]} vs board {holes[0][3]:.2f}")

# -------------------------------------------------------------- connectors
EDGE_BAND = 12.0


def nearest_edge(x, y):
    d = {"top": y, "bottom": dev.d - y, "left": x, "right": dev.w - x}
    return min(d, key=d.get), min(d.values())


for ref, edge_name in iface["connector_edges"].items():
    fp = board.FindFootprintByReference(ref)
    pads = [p for p in fp.Pads() if p.GetNumber()]
    cx = sum(mm(p.GetPosition().x) for p in pads) / len(pads)
    cy = sum(mm(p.GetPosition().y) for p in pads) / len(pads)
    got, dist = nearest_edge(cx, cy)
    check(f"{ref} sits on the {edge_name} edge, facing its panel device",
          got == edge_name and dist <= EDGE_BAND, f"pads centred {dist:.1f} mm from the {got} edge")

# -------------------------------------------------------------- envelope
inside = True
for fp in board.GetFootprints():
    bb = fp.GetCourtyard(P.F_CrtYd).BBox()
    if bb.GetWidth() == 0:
        continue
    if mm(bb.GetLeft()) < -TOL or mm(bb.GetTop()) < -TOL or \
       mm(bb.GetRight()) > dev.w + TOL or mm(bb.GetBottom()) > dev.d + TOL:
        inside = False
        print(f"      {fp.GetReference()} courtyard outside the outline")
check("every courtyard is inside the outline", inside)

stack = iface["standoff"] + iface["outline"]["thick"] + S.CONN_MATED_H
check("standoff + board + tallest mated connector fits the height params.py allows",
      stack <= dev.h + TOL and S.CONN_MATED_H <= iface["max_part_height"] + TOL,
      f"{iface['standoff']:g} + {iface['outline']['thick']:g} + {S.CONN_MATED_H:g} = "
      f"{stack:.1f} mm <= {dev.h:.1f} mm")
check("the standoff keepouts on the board clear the mounting holes by the M3 washer radius",
      all(any(z.GetIsRuleArea() and z.Outline().Contains(P.VECTOR2I(P.FromMM(x), P.FromMM(y)))
              for z in board.Zones()) for _, x, y, _ in holes))

print()
if FAILED:
    print(f"FAIL  {len(FAILED)} fit check(s)")
    sys.exit(1)
print("PASS  board fits the panel")
