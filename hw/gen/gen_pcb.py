#!/usr/bin/env python3
"""Generate rover-panel-supervisor.kicad_pcb.

Run with KiCad's own interpreter (pcbnew is not importable from system python):
    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/\
Versions/3.9/bin/python3 gen/gen_pcb.py

Three inputs, and the board is only as right as the weakest of them:

  panel_interface.json  the outline, the corner radius and the four mounting
                        holes.  NOT typed here: rover-power-panel/scripts/
                        params.py wrote them, and the plate was drilled from
                        the same numbers.
  the netlist           every part, value, footprint and connection.
  PLACE below           where each part sits.  This is the layout design.
                        The copper between the parts is searched for by
                        autoroute.py, and then judged by kicad-cli DRC.

Board frame: origin top-left as seen from the bay hatch, +x right, +y down.
The TOP edge faces K1 and R1, the LEFT edge faces the shunt RS1, the RIGHT
edge faces J1.  The connectors sit on those edges because the interface says
so, and check_fit.py reads them back to make sure.
"""
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "design")))
import kipcb  # noqa: E402
import autoroute as AR  # noqa: E402
import spec as S  # noqa: E402
import pcbnew as P  # noqa: E402
from kipcb import F_CU, B_CU  # noqa: E402

IFACE = json.load(open(os.path.join(HERE, "..", "..", "design", "panel_interface.json")))
W, H = IFACE["outline"]["w"], IFACE["outline"]["d"]
R_CORNER = IFACE["outline"]["corner_r"]
HOLES = [(h["u"], h["v"], h["board_dia"]) for h in IFACE["mounting_holes"]]
STANDOFF_KEEPOUT = 3.5          # radius: M3 washer / 5.5 mm hex standoff + margin

NAME = "rover-panel-supervisor"
b = kipcb.Board(os.path.join(HERE, "..", f"{NAME}.net"), W, H)
b.edge_rect(0, 0, W, H, r=R_CORNER)

# ================================================================ placement ==
# (ref, x, y, rot).  Grouped by what the parts DO; the comment on each group is
# why it sits where it does.
PLACE = [
    # --- mounting: from panel_interface.json, in its order --------------------
    *[(f"H{i+1}", u, v, 0) for i, (u, v, _) in enumerate(HOLES)],

    # --- P1 on the top edge: edge row = GND + E-stop/coil+, inner row travels -
    ("P1", 38.0, 3.2, 0),
    ("D1", 41.0, 14.2, 180),      # input TVS straight under the +24 V pins
    ("D6", 49.0, 14.2, 0),        # coil+ clamp, straight under the E-stop return

    # --- K1 coil drive, left of P1: COIL_NEG is one short run to Q1's tab ----
    ("Q1", 26.5, 7.0, 180),
    ("D5", 15.5, 6.3, 180),       # coil- clamp, on the drain

    ("R30", 30.5, 12.6, 0),
    ("R31", 26.0, 12.6, 0),

    # --- precharge switch, right of P1: PRE_OUT is P1.10 straight to the tab --
    ("Q6", 60.5, 7.0, 0),
    ("R34", 68.5, 3.0, 0),
    ("D7", 68.5, 5.8, 180),
    ("R33", 68.5, 8.6, 0),
    ("Q5", 68.0, 12.8, 90),
    ("R32", 62.5, 15.6, 0),
    ("Q4", 57.5, 15.2, 90),

    # --- 5 V buck, top right ------------------------------------------------
    ("D2", 76.5, 13.2, 180),
    ("C1", 79.2, 8.5, 180),       # input caps on the VIN side, left of U1
    ("C2", 83.6, 8.5, 180),
    ("U1", 89.5, 9.0, 0),
    ("R4", 84.2, 11.0, 180),      # ILIM and RT straps straight off their pins
    ("R3", 84.2, 13.6, 180),
    ("R1", 94.5, 13.0, 0),
    ("R2", 94.5, 15.6, 0),
    ("L1", 97.0, 4.2, 0),
    ("C4", 100.3, 10.2, 90),
    ("C3", 103.5, 10.8, 90),
    ("R5", 90.5, 17.8, 0),
    ("D3", 98.5, 14.8, 0),

    # --- pack current: P2 on the left edge, the filter, then the INA228 ------
    ("P2", 5.5, 19.0, 0),
    ("R6", 12.2, 18.5, 0),
    ("R7", 12.2, 22.5, 0),
    ("C5", 15.0, 20.5, 90),
    ("U2", 19.0, 26.0, 90),    # Kelvin pins up, I2C and ground down
    ("C6", 21.8, 20.8, 0),

    # --- comparators: U3 in the middle, its dividers either side ------------
    ("U3", 45.0, 29.5, 0),
    ("C14", 40.0, 24.0, 0),
    # left: precharge ratio (VA / VS) and the fault timer
    ("R12", 35.0, 19.5, 0),
    ("R13", 35.0, 22.3, 0),
    ("C9", 35.0, 25.1, 0),
    ("R16", 35.0, 27.9, 0),
    ("R14", 35.0, 30.7, 0),
    ("R15", 35.0, 33.5, 0),
    ("C10", 35.0, 36.3, 0),
    ("R26", 29.5, 27.9, 0),
    ("R17", 29.5, 30.7, 0),
    ("C11", 29.5, 33.7, 0),
    ("D4", 29.5, 36.7, 0),
    ("R27", 29.5, 39.5, 0),
    ("R10", 29.5, 19.5, 0),
    ("R11", 29.5, 22.3, 0),
    ("C8", 29.5, 25.1, 0),
    # right: E-stop sense, ARM receiver, VREF
    ("R18", 55.0, 19.5, 0),
    ("R19", 55.0, 22.3, 0),
    ("C12", 55.0, 25.1, 0),
    ("R20", 55.0, 27.9, 0),
    ("R21", 55.0, 30.7, 0),
    ("R22", 55.0, 33.5, 0),
    ("C13", 55.0, 36.3, 0),
    ("R23", 55.0, 39.1, 0),
    ("R8", 60.5, 19.5, 0),
    ("R9", 60.5, 22.3, 0),
    ("C7", 60.5, 25.1, 0),
    ("R24", 60.5, 27.9, 0),
    ("R25", 60.5, 30.7, 0),

    # --- interlock latch and K1 gate -----------------------------------------
    ("U4", 68.5, 21.0, 0),
    ("C15", 68.5, 17.8, 0),
    ("R28", 68.5, 25.0, 0),
    ("C17", 68.5, 27.8, 0),
    ("U5", 76.0, 25.0, 0),
    ("C16", 76.0, 21.2, 0),
    ("R29", 76.0, 29.5, 0),
    ("C18", 76.0, 32.3, 0),
    ("Q2", 70.5, 33.0, 0),
    ("Q3", 70.5, 37.5, 0),

    # --- status: LEDs along the bottom edge, open-drain + ESD at P3 ----------
    ("Q7", 64.0, 38.5, 0),
    ("R35", 60.5, 42.5, 0),
    ("D8", 65.5, 42.5, 0),
    ("Q8", 79.0, 38.5, 0),
    ("R36", 75.5, 42.5, 0),
    ("D9", 80.5, 42.5, 0),
    ("Q9", 90.0, 38.5, 0),
    ("R37", 86.5, 42.5, 0),
    ("D10", 91.5, 42.5, 0),
    ("R38", 47.5, 42.8, 0),
    ("D11", 52.0, 42.8, 0),

    ("P3", 101.0, 31.0, 90),
    ("Q10", 86.5, 21.0, 0),
    ("Q11", 86.5, 26.0, 0),
    ("Q12", 86.5, 31.0, 0),
    # ESD column in the same top-to-bottom order as the P3 pins it protects
    ("D15", 94.0, 20.0, 0),       # P3.4 ALERT
    ("D18", 94.0, 22.8, 0),       # P3.8 ESTOP_OK
    ("D14", 94.0, 25.6, 0),       # P3.3 SCL
    ("D17", 94.0, 28.4, 0),       # P3.7 FAULT
    ("D13", 94.0, 31.2, 0),       # P3.2 SDA
    ("D16", 94.0, 34.0, 0),       # P3.6 K1_ON
    ("D12", 94.0, 36.8, 0),       # P3.1 ARM

    # --- test points: along the bottom-left, where a probe can reach --------
    ("TP1", 97.5, 38.8, 0),
    ("TP2", 11.0, 42.8, 0),
    ("TP3", 17.0, 42.8, 0),
    ("TP4", 23.0, 42.8, 0),
    ("TP5", 29.0, 42.8, 0),
    ("TP6", 35.0, 42.8, 0),
    ("TP7", 41.0, 42.8, 0),
]

for ref, x, y, rot in PLACE:
    b.place(ref, x, y, rot)
    b.ref_style(ref, size=0.8, thickness=0.12, hide=True)
    b.hide_fp_text(ref, value=True)
missing = sorted(set(b.comps) - set(b.fps))
if missing:
    raise SystemExit("parts in the netlist with no placement: " + ", ".join(missing))


# ======================================================== placement checks ==
def check_courtyards():
    """No two courtyards overlap, and none leaves the board -- before routing,
    because a router fed an overlapping placement burns minutes to fail."""
    boxes = []
    for ref, fp in b.fps.items():
        bb = fp.GetCourtyard(P.F_CrtYd).BBox()
        if bb.GetWidth() == 0:
            continue
        boxes.append((ref, kipcb.mm(bb.GetLeft()), kipcb.mm(bb.GetTop()),
                      kipcb.mm(bb.GetRight()), kipcb.mm(bb.GetBottom())))
    bad = []
    for i in range(len(boxes)):
        r1, a0, a1, a2, a3 = boxes[i]
        if a0 < 0 or a1 < 0 or a2 > W or a3 > H:
            bad.append(f"{r1} courtyard leaves the board ({a0:.1f},{a1:.1f})-({a2:.1f},{a3:.1f})")
        for j in range(i + 1, len(boxes)):
            r2, b0, b1, b2, b3 = boxes[j]
            if r1.startswith("H") and r2.startswith("H"):
                continue
            if a0 < b2 and b0 < a2 and a1 < b3 and b1 < a3:
                bad.append(f"{r1} overlaps {r2}")
    for u, v, _ in HOLES:
        for r1, a0, a1, a2, a3 in boxes:
            if r1.startswith("H"):
                continue
            dx = max(a0 - u, 0, u - a2)
            dy = max(a1 - v, 0, v - a3)
            if math.hypot(dx, dy) < STANDOFF_KEEPOUT:
                bad.append(f"{r1} is inside the standoff keepout at ({u},{v})")
    if bad:
        raise SystemExit("PLACEMENT:\n  " + "\n  ".join(bad))


check_courtyards()

# ================================================================== routing ==
import gen_pro  # noqa: E402  -- one definition of the net classes, not two

CLASS_OF = {"/" + n: cls for cls, nets in gen_pro.CLASSES.items() for n in nets}
CLEAR = {"Power": S.CLEARANCE_POWER, "Pack": S.CLEARANCE_POWER, "Kelvin": 0.2, None: 0.2}


def clearance_of(net):
    return CLEAR[CLASS_OF.get(net)]


# Parts that carry the coil inrush or the precharge current. A connection
# between two of them is a power connection (1.0 mm); a connection from one of
# them to anything else is a sense tap and is routed thin.
POWER_REFS = {"P1", "Q1", "Q6", "D1", "D5", "D6"}      # D2 feeds only the 5 V buck


def width_for(net, ra, rb):
    cls = CLASS_OF.get(net)
    if cls == "Power":
        return S.W_POWER if (ra in POWER_REFS and rb in POWER_REFS) else 0.3
    if net == "/BUCK_SW":
        return 0.4
    if net in ("/VIN_BUCK", "/+5V"):
        return 0.4
    if cls == "Kelvin":
        return 0.3
    return S.W_SIGNAL


rt = None

# pad bookkeeping ---------------------------------------------------------------
PADS = {}          # net -> [(ref, pad)]
for ref, fp in b.fps.items():
    for pad in fp.Pads():
        n = pad.GetNetname()
        if n:
            PADS.setdefault(n, []).append((ref, pad))


def pxy(pad):
    q = pad.GetPosition()
    return (round(kipcb.mm(q.x), 4), round(kipcb.mm(q.y), 4))


def pad_cells(pad):
    """Grid cells inside a pad's copper, per layer."""
    import numpy as np
    out = []
    for L in AR.LAYERS:
        if not pad.IsOnLayer(L):
            continue
        for poly in rt.pad_polys(pad, L):
            xs = [q[0] for q in poly]
            ys = [q[1] for q in poly]
            win, X, Y = rt._window(min(xs), min(ys), max(xs), max(ys))
            inside = np.zeros(X.shape, dtype=bool)
            n = len(poly)
            for k in range(n):
                ax, ay = poly[k]
                bx, by = poly[(k + 1) % n]
                cond = ((ay > Y) != (by > Y))
                with np.errstate(divide="ignore", invalid="ignore"):
                    xint = (bx - ax) * (Y - ay) / (by - ay + 1e-30) + ax
                inside ^= cond & (X < xint)
            j0, _, i0, _ = win
            for jj, ii in zip(*np.nonzero(inside)):
                out.append((L, j0 + int(jj), i0 + int(ii)))
    if not out:          # a pad narrower than a grid cell: take its centre
        x, y = pxy(pad)
        j, i = rt.cell(x, y)
        out = [(L, j, i) for L in AR.LAYERS if pad.IsOnLayer(L)]
    return out


# fine-pitch escape stubs --------------------------------------------------------
TERMINAL = {}      # (ref, padnumber, x, y) -> (cells, exact xy)


def fanout(ref, length=0.9):
    """Straight stubs out of a fine-pitch part, along each pad's own axis."""
    fp = b.fps[ref]
    c = fp.GetPosition()
    cx, cy = kipcb.mm(c.x), kipcb.mm(c.y)
    for pad in fp.Pads():
        net = pad.GetNetname()
        if not net or net.startswith("unconnected-") or pad.HasHole() or not pad.IsOnLayer(F_CU):
            continue
        x, y = pxy(pad)
        dx, dy = x - cx, y - cy
        bb = pad.GetBoundingBox()
        if abs(dx) >= abs(dy):
            half = kipcb.mm(bb.GetWidth()) / 2
            ex, ey = x + math.copysign(half + length, dx), y
        else:
            half = kipcb.mm(bb.GetHeight()) / 2
            ex, ey = x, y + math.copysign(half + length, dy)
        ex = round(round(ex / rt.p) * rt.p, 4)
        ey = round(round(ey / rt.p) * rt.p, 4)
        if net == "GND" and ref == "U1":
            continue              # the thermal pad's vias carry U1's ground
        rt.add_track(net, F_CU, (x, y), (ex, ey), 0.2)
        j, i = rt.cell(ex, ey)
        TERMINAL[(ref, pad.GetNumber(), x, y)] = ([(F_CU, j, i)], (ex, ey))


def fresh_router():
    """A clean slate: no copper on the board, pads and keepouts painted, escapes
    re-made. Routing restarts from here whenever a net fails."""
    global rt
    for t in list(b.b.GetTracks()):
        b.b.Remove(t)
    TERMINAL.clear()
    # back_penalty: every millimetre of track on B.Cu is a cut in the ground
    # plane, and enough cuts fence a ground via into a pocket of its own
    rt = AR.Router(b, W, H, clearance_of, pitch=0.1, c0=0.2, t0=S.W_SIGNAL, margin=0.05,
                   edge_clearance=S.FAB_MIN_EDGE_CLEARANCE, back_penalty=2.5)
    rt.add_pads()
    for u, v, _ in HOLES:
        rt.keepout_circle((u, v), STANDOFF_KEEPOUT)
    for ref in ("U2", "U5", "U1"):
        fanout(ref)


def terminal(ref, pad):
    x, y = pxy(pad)
    key = (ref, pad.GetNumber(), x, y)
    if key in TERMINAL:
        return TERMINAL[key]
    return pad_cells(pad), None


# ground vias for every SMD ground pad ----------------------------------------
def gnd_vias(escaped):
    """Each surface-mount ground pad gets its own via to the back pour, found by
    a short search -- never a via-in-pad, never through someone else's copper.

    Called twice. Ordinary pads first, so their vias sit right beside them.
    Pads on a fine-pitch escape LAST (escaped=True): a ground via dropped at
    the end of an INA228 stub lands exactly where the neighbouring signal needs
    to leave, and walls it in."""
    import numpy as np
    n = 0
    for ref, pad in PADS.get("GND", []):
        if pad.HasHole() or not pad.IsOnLayer(F_CU):
            continue
        if ref == "U1" and pad.GetNumber() == "11":
            continue
        if ((ref, pad.GetNumber(), *pxy(pad)) in TERMINAL) != escaped:
            continue
        blk = rt.blocked("GND", 0.25, 0.2)
        vok = rt.via_ok("GND", 0.2)
        cells, exact = terminal(ref, pad)
        for L, j, i in cells:
            blk[L][j, i] = False
        x, y = pxy(pad)
        # a via must not sit on the pad itself: paste would wick down it
        goal = {F_CU: vok.copy(), B_CU: np.zeros_like(vok)}
        j0, i0 = rt.cell(x, y)
        rpad = int(math.ceil((max(kipcb.mm(pad.GetBoundingBox().GetWidth()),
                                   kipcb.mm(pad.GetBoundingBox().GetHeight())) / 2 + 0.35) / rt.p))
        goal[F_CU][max(0, j0 - rpad):j0 + rpad + 1, max(0, i0 - rpad):i0 + rpad + 1] = False
        path = rt.astar([c for c in cells if c[0] == F_CU], goal, blk, vok,
                        allow_layers=(F_CU,), max_expand=20000, heur_pts=None)
        if path is None:
            raise AR.RouteError(f"no room for a ground via at {ref}.{pad.GetNumber()}")
        start = exact if exact else (x, y)
        L, j, i = path[-1]
        vx, vy = rt.xy(j, i)
        rt.emit("GND", path, 0.25, start_xy=start)
        # the search may end on a ground via another pad already dropped: share
        # it, do not drill the same hole twice
        if not any(vn == "GND" and abs(x_ - vx) < 1e-6 and abs(y_ - vy) < 1e-6
                   for vn, x_, y_ in rt.vias):
            rt.add_via("GND", vx, vy)
            n += 1
    return n


# the net router -----------------------------------------------------------------
def route_net(net):
    import numpy as np
    pads = PADS[net]
    if len(pads) < 2:
        return 0
    clr = clearance_of(net)
    # own pads are never obstacles to their own net
    terms = []
    for ref, pad in pads:
        cells, exact = terminal(ref, pad)
        terms.append((ref, pad, cells, exact if exact else pxy(pad)))
    # power terminals first, so taps attach to a finished power path
    terms.sort(key=lambda t: (t[0] not in POWER_REFS, t[0]))
    tree = {L: np.zeros((rt.ny, rt.nx), dtype=bool) for L in AR.LAYERS}
    tree_refs = []
    tree_pts = []

    def add_tree(cells, pt, ref):
        for L, j, i in cells:
            tree[L][j, i] = True
        tree_pts.append(pt)
        tree_refs.append(ref)

    r0 = terms.pop(0)
    add_tree(r0[2], r0[3], r0[0])
    segs = 0
    while terms:
        # nearest remaining terminal to the tree
        k = min(range(len(terms)), key=lambda t: min(
            math.hypot(terms[t][3][0] - q[0], terms[t][3][1] - q[1]) for q in tree_pts))
        ref, pad, cells, pt = terms.pop(k)
        near = min(range(len(tree_pts)),
                   key=lambda t: math.hypot(pt[0] - tree_pts[t][0], pt[1] - tree_pts[t][1]))
        w = width_for(net, ref, tree_refs[near])
        if (ref, pad.GetNumber(), *pxy(pad)) in TERMINAL:
            # out of a fine-pitch escape: a wide trace would not clear the
            # neighbouring stubs, and nothing that leaves an SSOP carries amps
            w = min(w, 0.25)
        blk = rt.blocked(net, w, clr)
        for L, j, i in cells:
            blk[L][j, i] = False
        vok = rt.via_ok(net, clr)
        path = rt.astar(cells, tree, blk, vok, heur_pts=tree_pts)
        if path is None:
            raise AR.RouteError(f"{net}: could not connect {ref}.{pad.GetNumber()} "
                                f"at ({pt[0]:.1f},{pt[1]:.1f})")
        segs += rt.emit(net, path, w, start_xy=pt)
        # the new copper joins the tree (a generous band around the path)
        for L, j, i in path:
            tree[L][max(0, j - 1):j + 2, max(0, i - 1):i + 2] = True
        add_tree(cells, pt, ref)
    return segs


def dump_debug(err, path=os.path.join(HERE, "..", ".debug", "route.json")):
    """On failure, write what the router saw so gen/debug_render.py can draw it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fps = []
    for ref, fp in b.fps.items():
        cy = fp.GetCourtyard(P.F_CrtYd).BBox()
        pads = []
        for pad in fp.Pads():
            bb = pad.GetBoundingBox()
            pads.append([kipcb.mm(bb.GetLeft()), kipcb.mm(bb.GetTop()),
                         kipcb.mm(bb.GetRight()), kipcb.mm(bb.GetBottom()),
                         pad.GetNetname(), int(pad.HasHole())])
        fps.append(dict(ref=ref, crt=[kipcb.mm(cy.GetLeft()), kipcb.mm(cy.GetTop()),
                                      kipcb.mm(cy.GetRight()), kipcb.mm(cy.GetBottom())],
                        pads=pads))
    json.dump(dict(w=W, h=H, err=str(err), fps=fps,
                   tracks=[[n, int(L == B_CU), a, c, w_] for n, L, a, c, w_ in rt.tracks],
                   vias=rt.vias), open(path, "w"))
    import numpy as np
    np.save(path.replace(".json", "_F.npy"), rt.owner[F_CU])
    np.save(path.replace(".json", "_B.npy"), rt.owner[B_CU])
    print("  debug dump:", os.path.normpath(path))


# The nets that carry current, and the Kelvin pair, get first choice of copper.
# Everything else goes shortest first: a two-pin strap routed after a long net
# finds itself walled in, while a long net routed after the straps just goes
# round them.
ORDER = ["/+24V_IN", "/COIL_NEG", "/PRE_OUT", "/COIL_POS",
         "/KELVIN_P", "/KELVIN_N", "/INA_INP", "/INA_INN"]


def span(net):
    xs = [pxy(p)[0] for _, p in PADS[net]]
    ys = [pxy(p)[1] for _, p in PADS[net]]
    return (max(xs) - min(xs)) + (max(ys) - min(ys))


REST = sorted((n for n in PADS if n not in ORDER and n != "GND"
               and not n.startswith("unconnected-")), key=span)


def route_all(promoted):
    """One complete attempt. `promoted` nets jump the queue, in the order they
    failed -- the cheapest form of rip-up-and-retry there is: when a net cannot
    get out, let it go before whatever walled it in. "GND" in the list means
    the escaped ground vias go before everything but the power nets."""
    fresh_router()
    n = gnd_vias(escaped=False)
    order = [x for x in promoted if x in ORDER] + [x for x in ORDER if x not in promoted]
    order += [x for x in promoted if x not in ORDER] + [x for x in REST if x not in promoted]
    early = "GND" in promoted
    order = [x for x in order if x != "GND"]
    for k, net in enumerate(order):
        if early and k == len(ORDER):
            n += gnd_vias(escaped=True)
        route_net(net)
    if not early:
        n += gnd_vias(escaped=True)
    return n


t0 = time.time()
promoted = []
for attempt in range(1, 26):
    try:
        n_gv = route_all(promoted)
        break
    except AR.RouteError as e:
        net = str(e).split(":")[0]
        if not net.startswith("/"):           # a ground-via failure
            if "GND" in promoted:
                dump_debug(e)
                raise SystemExit(f"ROUTING FAILED: {e}")
            net = "GND"
        print(f"  attempt {attempt}: {e} -- promoting {net}", flush=True)
        if net in promoted:
            promoted.remove(net)
        promoted.insert(0, net)
else:
    dump_debug(e)
    raise SystemExit(f"ROUTING FAILED after {attempt} attempts: {e}")
print(f"  attempt {attempt} routed every net", flush=True)
print(f"  routing done in {time.time()-t0:.0f} s, {n_gv} ground vias")


# ================================================================ ground =====
def stitch(pitch=4.0):
    import numpy as np
    vok = rt.via_ok("GND", 0.2)
    # stay away from other vias so drills keep their spacing
    n = 0
    y = 2.0
    while y < H - 1.0:
        x = 2.0
        while x < W - 1.0:
            j, i = rt.cell(x, y)
            r = int(1.2 / rt.p)
            if vok[max(0, j - r):j + r + 1, max(0, i - r):i + r + 1].all():
                rt.add_via("GND", x, y)
                vok = rt.via_ok("GND", 0.2)
                n += 1
            x += pitch
        y += pitch
    return n


n_st = stitch()
INSET = 0.5
for layer in (F_CU, B_CU):
    b.rect_zone(INSET, INSET, W - INSET, H - INSET, layer, "GND", priority=0)


def standoff_keepout(u, v, r):
    z = P.ZONE(b.b)
    ls = P.LSET()
    ls.addLayer(F_CU)
    ls.addLayer(B_CU)
    z.SetLayerSet(ls)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowCopperPour(True)
    z.SetDoNotAllowTracks(True)
    z.SetDoNotAllowVias(True)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    z.SetZoneName("STANDOFF KEEPOUT")
    o = z.Outline()
    o.NewOutline()
    for k in range(32):
        a = 2 * math.pi * k / 32
        o.Append(kipcb.MM(u + r * math.cos(a)), kipcb.MM(v + r * math.sin(a)))
    b.b.Add(z)


for u, v, _ in HOLES:
    standoff_keepout(u, v, STANDOFF_KEEPOUT)

# Tent every via: no bare copper rings under silkscreen or beside a hand-
# soldered pad, and nothing for a solder bridge to reach. Set before the
# labels are placed, because a tented via is not a silkscreen obstacle.
ds = b.b.GetDesignSettings()
for attr in ("m_TentViasFront", "m_TentViasBack"):
    if hasattr(ds, attr):
        setattr(ds, attr, True)

# ============================================================== silkscreen ==
def ring(x, y, rot=0, radii=(0.0, 1.0, 1.8, 2.6, 3.6, 4.8)):
    """Positions around an anchor, nearest first (see can-iso-breakout)."""
    out = []
    for r in radii:
        for dx, dy in ((0, 0), (0, -1), (0, 1), (1, 0), (-1, 0),
                       (1, -1), (-1, -1), (1, 1), (-1, 1)):
            out.append((round(x + dx * r, 2), round(y + dy * r, 2), rot))
    return out


LABELS = [
    # text, anchor x, y, size, bold -- anchored beside the thing it names
    ("rover-panel-supervisor  rev %s" % S.REV, 3.0, 30.5, 1.0, True),
    ("precharge / K1 interlock / INA228", 3.0, 32.3, 0.8, False),
    ("P1 PWR", 34.0, 11.8, 0.8, True),
    ("P2 RS1", 1.8, 26.8, 0.8, True),
    ("P3 J1", 97.5, 15.0, 0.8, True),
]
for text, x, y, size, bold in LABELS:
    try:
        b.label(text, ring(x, y), size=size, bold=bold)
    except SystemExit as e:
        print("  silk:", e)
# An LED label that wanders is worse than none: it names the wrong light. So
# LED labels get a tight search -- above the LED or beside it -- and fail loudly.
for ref, text in (("D8", "K1"), ("D9", "PRE"), ("D10", "FLT"), ("D11", "ESTOP"), ("D3", "5V")):
    c = b.fps[ref].GetPosition()
    x, y = kipcb.mm(c.x), kipcb.mm(c.y)
    tight = (ring(x - 1.0, y - 2.2, radii=(0.0, 0.8, 1.4))
             + ring(x + 2.2, y - 0.4, radii=(0.0, 0.8)) + ring(x - 6.0, y - 0.4, radii=(0.0, 0.8))
             + [(x - 1.5 + dx, y + 1.75, 0) for dx in (0.0, 0.5, -0.5, 1.0, -1.0, 1.5, 2.0)])
    b.label(text, tight, size=0.8, bold=True)
for tp in ("TP1", "TP2", "TP3", "TP4", "TP5", "TP6", "TP7"):
    x, y = pxy(list(b.fps[tp].Pads())[0])
    net = b.padnet(tp, "1").lstrip("/")
    try:
        b.label(net, ring(x - 1.0, y - 2.0, radii=(0.0, 0.8, 1.6)) + ring(x + 1.6, y - 0.4, radii=(0.0, 0.6)),
                size=0.8)
    except SystemExit as e:
        print("  silk:", e)

# =================================================================== output ==
def repair_ground(names):
    """Wire a pad the pour could not reach to the nearest ground pad it can.

    The pour is computed after routing, so the router cannot see that a via
    it dropped beside an INA228 pin landed in a pocket of back copper fenced
    in by signal tracks. This is the after-the-fact fix: a real track, found
    by the same search, from the stranded pad to any pad in the connected
    part of the net."""
    import numpy as np
    good = [(r, pd) for r, pd in PADS["GND"]
            if f"{r}.{pd.GetNumber()}" not in names and not r.startswith("H")]
    tree = {L: np.zeros((rt.ny, rt.nx), dtype=bool) for L in AR.LAYERS}
    pts = []
    for r, pd in good:
        for L, j, i in pad_cells(pd):
            tree[L][j, i] = True
        pts.append(pxy(pd))
    for name in names:
        ref, num = name.split(".")
        pad = next(pd for r, pd in PADS["GND"] if r == ref and pd.GetNumber() == num)
        cells, exact = terminal(ref, pad)
        blk = rt.blocked("GND", S.W_SIGNAL, 0.2)
        for L, j, i in cells:
            blk[L][j, i] = False
        path = rt.astar(cells, tree, blk, rt.via_ok("GND", 0.2), heur_pts=pts)
        if path is None:
            dump_debug(f"GROUND POUR does not reach {name}, and no track can")
            raise SystemExit(f"GROUND POUR does not reach {name}, and no track can")
        rt.emit("GND", path, S.W_SIGNAL, start_xy=exact if exact else pxy(pad))
        print(f"  ground repair: {name} wired to the pour ({len(path)} cells)")


nz = b.fill(clearance=0.25, clearance_of=clearance_of)
for _ in range(3):
    if not b.stranded:
        break
    repair_ground(b.stranded)
    nz = b.fill(clearance=0.25, clearance_of=clearance_of)
if b.stranded:
    raise SystemExit("GROUND POUR does not reach: " + ", ".join(b.stranded))
out = os.path.normpath(os.path.join(HERE, "..", f"{NAME}.kicad_pcb"))
b.save(out)
print(f"  board {W:.0f} x {H:.0f} mm, 2 layer, outline and holes from panel_interface.json")
print(f"  {len(rt.tracks)} track segments, {len(rt.vias)} vias ({n_st} stitching)")
print("wrote", out)
