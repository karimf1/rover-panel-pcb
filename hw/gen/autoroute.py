"""A two-layer grid router for a generated board.

can-iso-breakout and sync-buck were routed by hand, one coordinate at a time.
That is fine for thirty parts. This board has a hundred and six, and a hand
route that has to be re-done every time a part moves is a hand route that
stops being re-done. So the geometry is placed by hand -- placement is the
design -- and the copper between the pads is searched for.

How it works, in the order it matters:

  * The board is a 0.1 mm grid per copper layer. Every cell holds the net
    that OWNS it (its copper plus that net's clearance halo), 0 for free, or
    -1 for "two nets' halos overlap here / board edge / keepout".
  * Halos are painted at the obstacle's own net-class clearance. A net being
    routed dilates the obstacle map by however much its own width and
    clearance exceed the minimum, so a 1 mm power trace keeps 0.3 mm from
    everything and a 0.2 mm signal trace can still thread a 0.5 mm-pitch IC.
  * Fine-pitch pads get a straight escape stub along their own axis first:
    a stub along a pad's centreline has exactly the pad's clearance to its
    neighbours, which a grid path starting inside the pad does not.
  * Each connection is an A* search from one pad to the net's copper routed
    so far, 8-connected, with a via cost and a back-layer penalty (B.Cu is
    the ground plane; every track on it cuts the plane).
  * Nothing here is trusted. kicad-cli DRC checks the result with the real
    clearance engine, and gen_pcb.py refuses to write a board with an
    unrouted connection.
"""
import heapq
import math

import numpy as np
import pcbnew as P

import kipcb

MM = kipcb.MM
F_CU, B_CU = P.F_Cu, P.B_Cu
LAYERS = (F_CU, B_CU)
SQ2 = math.sqrt(2.0)
DIRS = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
        (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2)]


class RouteError(RuntimeError):
    pass


def disk(r_cells):
    r = int(math.ceil(r_cells))
    return [(dx, dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
            if dx * dx + dy * dy <= r_cells * r_cells + 1e-9]


def dilate(mask, r_cells):
    """Binary dilation by a disk, with plain numpy shifts (no scipy in KiCad)."""
    if r_cells <= 0:
        return mask.copy()
    out = mask.copy()
    h, w = mask.shape
    for dx, dy in disk(r_cells):
        if dx == 0 and dy == 0:
            continue
        ys0, ys1 = max(0, dy), h + min(0, dy)
        xs0, xs1 = max(0, dx), w + min(0, dx)
        out[ys0:ys1, xs0:xs1] |= mask[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


class Router:
    def __init__(self, board, w, h, clearance_of, pitch=0.1, c0=0.2, t0=0.2,
                 margin=0.03, edge_clearance=0.3, via_d=0.6, via_drill=0.3,
                 via_cost=30.0, back_penalty=1.6):
        self.bd = board            # kipcb.Board
        self.p = pitch
        self.nx = int(round(w / pitch)) + 1
        self.ny = int(round(h / pitch)) + 1
        self.clr = clearance_of    # netname -> clearance (mm)
        self.c0, self.t0, self.margin = c0, t0, margin
        self.via_d, self.via_drill = via_d, via_drill
        self.via_cost, self.back_penalty = via_cost, back_penalty
        self.owner = {L: np.zeros((self.ny, self.nx), dtype=np.int32) for L in LAYERS}
        self.netid, self.netname = {}, {}
        self.tracks = []           # (net, layer, (x1,y1), (x2,y2), width)
        self.vias = []             # (net, x, y)
        # drilled holes must keep min_hole_to_hole from each other whatever
        # their nets -- two ground vias 0.3 mm apart are the same net and still
        # a broken drill bit
        self.hole_block = np.zeros((self.ny, self.nx), dtype=bool)
        self.hole_to_hole = 0.5
        # the board edge is everyone's keepout
        e = int(math.ceil((edge_clearance + t0 / 2 + margin) / pitch))
        for L in LAYERS:
            o = self.owner[L]
            o[:e, :] = -1
            o[-e:, :] = -1
            o[:, :e] = -1
            o[:, -e:] = -1

    # ----------------------------------------------------------------- nets
    def nid(self, name):
        if name not in self.netid:
            i = len(self.netid) + 1
            self.netid[name] = i
            self.netname[i] = name
        return self.netid[name]

    def halo(self, netname):
        c = self.clr(netname) if netname else self.c0
        return c + self.t0 / 2 + self.margin

    # ------------------------------------------------------------ painting
    def _window(self, x0, y0, x1, y1):
        p = self.p
        i0 = max(0, int(math.floor(x0 / p)))
        i1 = min(self.nx - 1, int(math.ceil(x1 / p)))
        j0 = max(0, int(math.floor(y0 / p)))
        j1 = min(self.ny - 1, int(math.ceil(y1 / p)))
        xs = np.arange(i0, i1 + 1) * p
        ys = np.arange(j0, j1 + 1) * p
        X, Y = np.meshgrid(xs, ys)
        return (j0, j1, i0, i1), X, Y

    def _merge(self, L, win, mask, nid):
        j0, j1, i0, i1 = win
        sub = self.owner[L][j0:j1 + 1, i0:i1 + 1]
        free = mask & (sub == 0)
        clash = mask & (sub != 0) & (sub != nid)
        sub[free] = nid
        sub[clash] = -1

    def paint_segment(self, L, a, b, width, netname, r_extra=None):
        nid = self.nid(netname) if netname else -1
        r = (self.halo(netname) if r_extra is None else r_extra) + width / 2
        x0, x1 = min(a[0], b[0]) - r, max(a[0], b[0]) + r
        y0, y1 = min(a[1], b[1]) - r, max(a[1], b[1]) + r
        win, X, Y = self._window(x0, y0, x1, y1)
        vx, vy = b[0] - a[0], b[1] - a[1]
        l2 = vx * vx + vy * vy
        if l2 == 0:
            d = np.hypot(X - a[0], Y - a[1])
        else:
            t = np.clip(((X - a[0]) * vx + (Y - a[1]) * vy) / l2, 0, 1)
            d = np.hypot(X - (a[0] + t * vx), Y - (a[1] + t * vy))
        self._merge(L, win, d <= r + 1e-9, nid)

    def paint_circle(self, L, c, radius, netname):
        self.paint_segment(L, c, c, 2 * radius, netname, r_extra=0.0 if netname is None else None)

    def paint_poly(self, L, pts, netname, r=None):
        nid = self.nid(netname) if netname else -1
        r = self.halo(netname) if r is None else r
        xs = [q[0] for q in pts]
        ys = [q[1] for q in pts]
        win, X, Y = self._window(min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r)
        inside = np.zeros(X.shape, dtype=bool)
        dmin = np.full(X.shape, np.inf)
        n = len(pts)
        for k in range(n):
            ax, ay = pts[k]
            bx, by = pts[(k + 1) % n]
            cond = ((ay > Y) != (by > Y))
            with np.errstate(divide="ignore", invalid="ignore"):
                xint = (bx - ax) * (Y - ay) / (by - ay + 1e-30) + ax
            inside ^= cond & (X < xint)
            vx, vy = bx - ax, by - ay
            l2 = vx * vx + vy * vy
            if l2 == 0:
                d = np.hypot(X - ax, Y - ay)
            else:
                t = np.clip(((X - ax) * vx + (Y - ay) * vy) / l2, 0, 1)
                d = np.hypot(X - (ax + t * vx), Y - (ay + t * vy))
            dmin = np.minimum(dmin, d)
        self._merge(L, win, inside | (dmin <= r + 1e-9), nid)
        return win, inside

    def pad_polys(self, pad, L):
        ps = P.SHAPE_POLY_SET()
        pad.TransformShapeToPolygon(ps, L, 0, MM(0.005), P.ERROR_INSIDE)
        out = []
        for i in range(ps.OutlineCount()):
            o = ps.Outline(i)
            out.append([(kipcb.mm(o.CPoint(j).x), kipcb.mm(o.CPoint(j).y))
                        for j in range(o.PointCount())])
        return out

    def add_pads(self):
        """Paint every pad and hole on the board."""
        for fp in self.bd.b.Footprints():
            for pad in fp.Pads():
                net = pad.GetNetname() or None
                for L in LAYERS:
                    if pad.IsOnLayer(L):
                        for poly in self.pad_polys(pad, L):
                            self.paint_poly(L, poly, net)
                if pad.HasHole():
                    hx, hy = kipcb.mm(pad.GetPosition().x), kipcb.mm(pad.GetPosition().y)
                    dr = kipcb.mm(pad.GetDrillSize().x) / 2
                    for L in LAYERS:
                        # a hole is a keepout for every OTHER net's vias and copper
                        self.paint_segment(L, (hx, hy), (hx, hy), 2 * dr, net)
                    self.block_hole((hx, hy), 2 * dr)

    def block_hole(self, c, drill):
        r = self.hole_to_hole + drill / 2 + self.via_drill / 2 + self.margin
        win, X, Y = self._window(c[0] - r, c[1] - r, c[0] + r, c[1] + r)
        j0, j1, i0, i1 = win
        self.hole_block[j0:j1 + 1, i0:i1 + 1] |= np.hypot(X - c[0], Y - c[1]) <= r

    def keepout_circle(self, c, radius):
        for L in LAYERS:
            self.paint_segment(L, c, c, 2 * radius, None, r_extra=0.0)

    # --------------------------------------------------------------- tracks
    def add_track(self, net, L, a, b, width):
        self.tracks.append((net, L, a, b, width))
        self.paint_segment(L, a, b, width, net)
        self.bd.track(a, b, width, L, net)

    def add_via(self, net, x, y):
        self.vias.append((net, x, y))
        for L in LAYERS:
            self.paint_segment(L, (x, y), (x, y), self.via_d, net)
        self.block_hole((x, y), self.via_drill)
        self.bd.via(x, y, net, drill=self.via_drill, size=self.via_d)

    # --------------------------------------------------------------- search
    def blocked(self, net, width, clearance):
        """Per-layer blocked masks for a track of this width and clearance."""
        nid = self.nid(net)
        extra = max(0.0, clearance - self.c0) + max(0.0, width / 2 - self.t0 / 2)
        rc = extra / self.p
        out = {}
        for L in LAYERS:
            o = self.owner[L]
            out[L] = dilate((o != 0) & (o != nid), rc)
        return out

    def via_ok(self, net, clearance):
        nid = self.nid(net)
        # a via is round and the grid is square: one extra cell of margin
        extra = max(0.0, clearance - self.c0) + max(0.0, self.via_d / 2 - self.t0 / 2) + self.p
        rc = extra / self.p
        m = self.hole_block.copy()
        for L in LAYERS:
            o = self.owner[L]
            m |= dilate((o != 0) & (o != nid), rc)
        ok = ~m
        # a via this net already owns IS a layer change: the search may use it
        # even though no new via could be drilled beside it
        for vn, x, y in self.vias:
            if vn == net:
                j, i = self.cell(x, y)
                ok[j, i] = True
        return ok

    def cell(self, x, y):
        return int(round(y / self.p)), int(round(x / self.p))

    def xy(self, j, i):
        return (round(i * self.p, 4), round(j * self.p, 4))

    def astar(self, starts, goal, blk, vok, allow_layers=LAYERS, max_expand=600000,
              heur_pts=None):
        """starts: [(L, j, i)]; goal: {L: bool array}. Returns [(L, j, i)]."""
        nL = {F_CU: 0, B_CU: 1}
        heur_pts = heur_pts or []
        hp = np.array(heur_pts) / self.p if heur_pts else None

        def h(j, i):
            if hp is None:
                return 0.0
            d = np.abs(hp[:, 0] - i), np.abs(hp[:, 1] - j)
            dx, dy = d
            return float(np.min(np.maximum(dx, dy) + (SQ2 - 1) * np.minimum(dx, dy)))

        g = {}
        parent = {}
        openh = []
        for s in starts:
            L, j, i = s
            if L not in allow_layers:
                continue
            g[s] = 0.0
            parent[s] = None
            heapq.heappush(openh, (h(j, i), 0.0, s))
        seen = set()
        n = 0
        hcache = {}
        while openh:
            f, gc, s = heapq.heappop(openh)
            if s in seen:
                continue
            seen.add(s)
            L, j, i = s
            if goal[L][j, i]:
                path = []
                while s is not None:
                    path.append(s)
                    s = parent[s]
                return path[::-1]
            n += 1
            if n > max_expand:
                return None
            pen = 1.0 if L == F_CU else self.back_penalty
            for dx, dy, c in DIRS:
                jj, ii = j + dy, i + dx
                if not (0 <= jj < self.ny and 0 <= ii < self.nx):
                    continue
                if blk[L][jj, ii] and not goal[L][jj, ii]:
                    continue
                if dx and dy and blk[L][j, ii] and blk[L][jj, i]:
                    continue       # no squeezing diagonally between two blocked cells
                t = (L, jj, ii)
                ng = gc + c * pen
                # a turn costs a little: straight runs, not staircases
                ps = parent.get(s)
                if ps is not None and ps[0] == L and (j - ps[1], i - ps[2]) != (dy, dx):
                    ng += 0.35
                if ng < g.get(t, 1e18):
                    g[t] = ng
                    parent[t] = s
                    key = (jj, ii)
                    hv = hcache.get(key)
                    if hv is None:
                        hv = h(jj, ii)
                        hcache[key] = hv
                    heapq.heappush(openh, (ng + hv, ng, t))
            if vok[j, i] and len(allow_layers) == 2:
                t = (B_CU if L == F_CU else F_CU, j, i)
                ng = gc + self.via_cost
                if ng < g.get(t, 1e18):
                    g[t] = ng
                    parent[t] = s
                    heapq.heappush(openh, (ng + h(j, i), ng, t))
        return None

    # ------------------------------------------------------------ emit path
    def emit(self, net, path, width, start_xy=None, end_xy=None):
        """Turn a cell path into tracks and vias, merging collinear steps."""
        runs = []          # (layer, [points])
        cur_L, pts = None, []
        for L, j, i in path:
            q = self.xy(j, i)
            if L != cur_L:
                if pts:
                    runs.append((cur_L, pts))
                    self.add_via(net, *pts[-1])
                    pts = [pts[-1]]
                cur_L = L
            if not pts or pts[-1] != q:
                pts.append(q)
        runs.append((cur_L, pts))
        if start_xy is not None:
            runs[0][1].insert(0, start_xy)
        if end_xy is not None:
            runs[-1][1].append(end_xy)
        n = 0
        for L, pts in runs:
            simp = [pts[0]]
            for k in range(1, len(pts) - 1):
                a, b, c = simp[-1], pts[k], pts[k + 1]
                if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) < 1e-9:
                    continue
                simp.append(b)
            simp.append(pts[-1])
            for a, b in zip(simp, simp[1:]):
                if a != b:
                    self.add_track(net, L, a, b, width)
                    n += 1
        return n
