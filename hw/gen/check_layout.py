#!/usr/bin/env python3
"""Layout rules DRC does not know about.

DRC checks that copper is legal. It does not check that the copper that
carries the coil inrush is actually the 1.0 mm copper, that the Kelvin pair
was routed as a pair, or that a decoupling capacitor sits next to the pin it
decouples -- a board can pass DRC with every one of those wrong. These are
the rules the router was asked to follow, checked on the saved .kicad_pcb.

Run with KiCad's interpreter:  make layout
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "design")))
try:
    import wx
    if wx.App.Get() is None:
        _APP = wx.App(False)
except ImportError:
    pass
import pcbnew as P  # noqa: E402

import spec as S  # noqa: E402

board = P.LoadBoard(os.path.join(HERE, "..", "rover-panel-supervisor.kicad_pcb"))
FAILED = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  -- ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


def mm(v):
    return P.ToMM(v)


def pads(ref, num):
    """Every pad with this number: a SOT-223 has pin 2 AND its tab."""
    out = [p for p in board.FindFootprintByReference(ref).Pads() if p.GetNumber() == str(num)]
    if not out:
        raise KeyError(f"{ref}.{num}")
    return out


def pad(ref, num):
    return pads(ref, num)[0]


def near(a, an, b, bn):
    return min(dist(pxy(p), pxy(q)) for p in pads(a, an) for q in pads(b, bn))


def pxy(p):
    q = p.GetPosition()
    return mm(q.x), mm(q.y)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


print("== layout: the rules the router was given ==")

# ------------------------------------------ 1. the current path is wide copper
POWER_PARTS = {"P1", "Q1", "Q6", "D1", "D5", "D6"}    # D2 carries only the buck's few mA


def wide_connected(net, min_w):
    """Are this net's power-part pads joined by copper at least min_w wide?

    Union-find over pads and the tracks of the net that meet the width, joined
    where a track end lies on a pad or on another track's end. A thin tap may
    hang off the power path; it may not BE the power path."""
    parent = {}

    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        parent[find(a)] = find(b)

    pads = [(f"{fp.GetReference()}.{p.GetNumber()}", p) for fp in board.GetFootprints()
            for p in fp.Pads() if p.GetNetname() == net and fp.GetReference() in POWER_PARTS]
    tracks = [t for t in board.GetTracks() if t.GetNetname() == net and t.Type() != P.PCB_VIA_T
              and mm(t.GetWidth()) >= min_w - 1e-6]
    vias = [t for t in board.GetTracks() if t.GetNetname() == net and t.Type() == P.PCB_VIA_T]
    ends = []
    for k, t in enumerate(tracks):
        for q in (t.GetStart(), t.GetEnd()):
            ends.append((("T", k), q))
    for k, v in enumerate(vias):
        ends.append((("V", k), v.GetPosition()))
    for (a, qa) in ends:
        find(a)
        for name, p in pads:
            if p.HitTest(qa):
                union(a, ("P", name))
        for (b, qb) in ends:
            if a != b and qa == qb:
                union(a, b)
    for name, p in pads:
        find(("P", name))
    groups = {}
    for name, _ in pads:
        groups.setdefault(find(("P", name)), []).append(name)
    return list(groups.values())


for net in ("/+24V_IN", "/COIL_NEG", "/PRE_OUT", "/COIL_POS"):
    groups = wide_connected(net, S.W_POWER)
    # pads of one part on the same net (P1.7/P1.8, Q1 tab + pin 2) may be joined
    # by the part itself
    parts = [{n.split(".")[0] for n in g} for g in groups]
    merged = True
    while merged and len(parts) > 1:
        merged = False
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                if parts[i] & parts[j]:
                    parts[i] |= parts.pop(j)
                    merged = True
                    break
            if merged:
                break
    check(f"{net.lstrip('/')}: every power part is joined by >= {S.W_POWER} mm copper",
          len(parts) == 1, " | ".join(",".join(sorted(p)) for p in parts))

# ------------------------------------------ 2. the Kelvin pair is a pair
def net_length(net):
    return sum(mm(t.GetLength()) for t in board.GetTracks()
               if t.GetNetname() == net and t.Type() != P.PCB_VIA_T)


lp, ln = net_length("/KELVIN_P"), net_length("/KELVIN_N")
check("Kelvin leads P2 -> R6/R7 are length-matched within 1.5 mm",
      abs(lp - ln) <= 1.5, f"{lp:.1f} vs {ln:.1f} mm")
check("Kelvin leads are short (the INA228 sits on its shunt connector)",
      max(lp, ln) <= 15.0, f"longest {max(lp, ln):.1f} mm")
lip, lin = net_length("/INA_INP"), net_length("/INA_INN")
check("filtered pair R6/R7 -> INA228 stays under 20 mm",
      max(lip, lin) <= 20.0, f"IN+ {lip:.1f} mm, IN- {lin:.1f} mm")

# ------------------------------------------ 3. parts sit where they work
NEAR = [
    ("D1", 1, "P1", 8, 12.0, "input TVS at the +24 V pins"),
    ("D6", 1, "P1", 3, 12.0, "coil+ clamp on the E-stop return"),
    ("D5", 1, "Q1", 2, 12.0, "coil- clamp on Q1's drain"),
    ("C2", 1, "U1", 2, 5.0, "buck input cap at VIN"),
    ("C1", 1, "U1", 2, 12.0, "buck bulk input cap"),
    ("C4", 1, "U1", 8, 12.0, "buck output cap at VOUT"),
    ("C6", 1, "U2", 6, 5.0, "INA228 VS decoupling"),
    ("C5", 1, "U2", 10, 8.0, "Kelvin filter cap at the INA228"),
    ("C14", 1, "U3", 3, 8.0, "LM339 decoupling"),
    ("C15", 1, "U4", 5, 5.0, "74LVC1G08 decoupling"),
    ("C16", 1, "U5", 8, 6.0, "74LVC1G74 decoupling"),
]
for a, an, b_, bn, lim, why in NEAR:
    d = near(a, an, b_, bn)
    check(f"{why}: {a} within {lim:g} mm of {b_}.{bn}", d <= lim, f"{d:.1f} mm")

ESD = {"D12": ("P3", 1), "D13": ("P3", 2), "D14": ("P3", 3), "D15": ("P3", 4),
       "D16": ("P3", 6), "D17": ("P3", 7), "D18": ("P3", 8)}
far = [(d, round(dist(pxy(pad(d, 1)), pxy(pad(*pn))), 1)) for d, pn in ESD.items()
       if dist(pxy(pad(d, 1)), pxy(pad(*pn))) > 15.0]
check("every ESD diode sits within 15 mm of the P3 pin it protects", not far, str(far))

# ------------------------------------------ 4. fab hygiene
ds = board.GetDesignSettings()
check("vias are tented on both sides", ds.m_TentViasFront and ds.m_TentViasBack)
thin = [t for t in board.GetTracks() if t.Type() != P.PCB_VIA_T
        and mm(t.GetWidth()) < S.FAB_MIN_TRACE - 1e-6]
check("no track below the fab minimum", not thin, f"{len(thin)} too thin")
back = sum(mm(t.GetLength()) for t in board.GetTracks()
           if t.Type() != P.PCB_VIA_T and t.GetLayer() == P.B_Cu)
front = sum(mm(t.GetLength()) for t in board.GetTracks()
            if t.Type() != P.PCB_VIA_T and t.GetLayer() == P.F_Cu)
check("the back layer is mostly ground plane (<= 35 % of track length on B.Cu)",
      back <= 0.35 * (back + front), f"{back:.0f} mm of {back+front:.0f} mm on B.Cu")

print()
if FAILED:
    print(f"FAIL  {len(FAILED)} layout check(s)")
    sys.exit(1)
print("PASS  layout rules")
