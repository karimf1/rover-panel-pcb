"""Thin helpers over pcbnew for building a board from a script.

The important idea: place footprints first, then ask pcbnew where the pads
actually landed (`pad()`), and route using those coordinates. Nothing here
recomputes a rotation by hand, so there is no transform to get wrong.
"""
import os, re, sys

# pcbnew reaches into wxWidgets for its progress reporters and asserts -- then
# segfaults, in ZONE_FILLER -- if no application object exists. One headless
# wx.App, created before pcbnew touches anything, is the whole fix. Without it
# the zones never fill and DRC reports every ground pad as unconnected.
try:
    import wx
    if wx.App.Get() is None:
        _WXAPP = wx.App(False)
except ImportError:
    _WXAPP = None

import pcbnew as P

MM = P.FromMM
def v(x, y):  return P.VECTOR2I(MM(x), MM(y))
def mm(i):    return P.ToMM(i)

FPDIRS = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"),
          "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints",
          "/usr/share/kicad/footprints"]

F_CU, B_CU = P.F_Cu, P.B_Cu
CU2 = [F_CU, B_CU]


def fp_path(lib):
    for d in FPDIRS:
        p = os.path.join(d, lib + ".pretty")
        if os.path.isdir(p): return p
    raise FileNotFoundError(lib)


def read_netlist(path):
    """(pads, comps) from a kicadsexpr netlist.

    pads:  {(ref, pad_number): net_name}   -- net names keep their leading "/"
           exactly as the schematic assigned them, so DRC's schematic-parity
           check compares equal strings. The auto-generated "unconnected-(...)"
           names are kept too: dropping them leaves the pad with no net at all,
           and schematic parity then reports it as missing.
    comps: {ref: {"value", "footprint", "tstamp"}} -- the schematic is the
           single source of truth for what part goes where, so the PCB reads
           its values and footprints from here rather than repeating them.
    """
    t = open(path).read()
    pads, comps = {}, {}
    for m in re.finditer(
            r'\(comp \(ref "([^"]+)"\)\s*\(value "([^"]*)"\)\s*'
            r'\(footprint "([^"]*)"\)[\s\S]*?\(tstamps "([^"]*)"\)\)', t):
        comps[m.group(1)] = {
            "value": m.group(2), "footprint": m.group(3), "tstamp": m.group(4),
            "dnp": '(property (name "dnp"))' in m.group(0),
            "no_bom": '(property (name "exclude_from_bom"))' in m.group(0)}
    sec = t[t.index("(nets"):]
    for m in re.finditer(r'\(net \(code "\d+"\) \(name "([^"]*)"\)[^\n]*\n'
                         r'((?:\s+\(node[^\n]*\n?)*)', sec):
        name = m.group(1)
        if not name:
            continue
        for ref, pad in re.findall(r'\(ref "([^"]+)"\) \(pin "([^"]+)"\)', m.group(2)):
            pads[(ref, pad)] = name
    return pads, comps


class Board:
    def __init__(self, netlist_path, w, h):
        self.b = P.BOARD()
        self.b.SetCopperLayerCount(2)
        self.w, self.h = w, h
        self.nl, self.comps = read_netlist(netlist_path)
        self._nets = {}
        self.fps = {}
        self._setup_rules()

    def _setup_rules(self):
        ds = self.b.GetDesignSettings()
        ds.SetCopperLayerCount(2)
        try:
            ds.m_TrackMinWidth   = MM(0.20)
            ds.m_ViasMinSize     = MM(0.45)
            ds.m_MinThroughDrill = MM(0.25)
            ds.m_HoleToHoleMin   = MM(0.25)
            ds.m_HoleClearance   = MM(0.20)
        except Exception:
            pass

    # ------------------------------------------------------------------- nets
    def net(self, name):
        if name not in self._nets:
            n = P.NETINFO_ITEM(self.b, name)
            self.b.Add(n)
            self._nets[name] = n
        return self._nets[name]

    # -------------------------------------------------------------- placement
    def place(self, ref, x, y, rot=0):
        """Place the footprint the SCHEMATIC assigned to `ref`.

        Library, footprint name and value all come from the netlist, and the
        footprint is linked back to its schematic symbol by UUID, so the board
        cannot disagree with the schematic about what part this is.
        """
        c = self.comps.get(ref)
        if c is None:
            raise KeyError(f"{ref} is not in the netlist -- run gen_sch.py first")
        lib, name = c["footprint"].split(":", 1)
        fp = P.FootprintLoad(fp_path(lib), name)
        if fp is None:
            raise RuntimeError(f"footprint not found: {c['footprint']}")
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetFPID(P.LIB_ID(lib, name))
        if c["tstamp"]:
            fp.SetPath(P.KIID_PATH("/" + c["tstamp"]))
        if c.get("dnp"):
            fp.SetDNP(True)
        if c.get("no_bom"):
            fp.SetExcludedFromBOM(True)
        fp.SetPosition(v(x, y))
        if rot:
            fp.SetOrientationDegrees(rot)
        self.b.Add(fp)
        self.fps[ref] = fp
        for pad in fp.Pads():
            key = (ref, pad.GetNumber())
            if key in self.nl:
                pad.SetNet(self.net(self.nl[key]))
        return fp

    def ref_style(self, ref, size=0.8, thickness=0.12, dx=None, dy=None,
                  rot=None, hide=False):
        """Reference designators, restyled.

        Footprint libraries place their refdes assuming the part has room
        around it. On a board this dense they collide, so they are shrunk to
        the fab's 0.8 mm minimum and nudged where the layout knows better.
        """
        f = self.fps[ref].Reference()
        f.SetTextSize(P.VECTOR2I(MM(size), MM(size)))
        f.SetTextThickness(MM(thickness))
        if hide: f.SetVisible(False)
        if rot is not None: f.SetTextAngle(P.EDA_ANGLE(rot, P.DEGREES_T))
        if dx is not None or dy is not None:
            c = self.fps[ref].GetPosition()
            f.SetPosition(P.VECTOR2I(c.x + MM(dx or 0), c.y + MM(dy or 0)))
        return f

    def pad(self, ref, num):
        """Where a pad actually is, in mm, after placement and rotation."""
        for p in self.fps[ref].Pads():
            if p.GetNumber() == str(num):
                q = p.GetPosition()
                return (round(mm(q.x), 4), round(mm(q.y), 4))
        raise KeyError(f"{ref} pad {num}")

    def padnet(self, ref, num):
        return self.nl.get((ref, str(num)))

    def hide_fp_text(self, ref, value=True, reference=False):
        fp = self.fps[ref]
        if value: fp.Value().SetVisible(False)
        if reference: fp.Reference().SetVisible(False)

    # ---------------------------------------------------------------- routing
    def track(self, p1, p2, width, layer=None, net=None):
        t = P.PCB_TRACK(self.b)
        t.SetStart(v(*p1)); t.SetEnd(v(*p2))
        t.SetWidth(MM(width))
        t.SetLayer(F_CU if layer is None else layer)
        if net is not None: t.SetNet(self.net(net) if isinstance(net, str) else net)
        self.b.Add(t)
        return t

    def path(self, pts, width, layer=None, net=None):
        for a, b in zip(pts, pts[1:]):
            if a != b:
                self.track(a, b, width, layer, net)

    def via(self, x, y, net=None, drill=0.3, size=0.6, layers=(None, None)):
        vi = P.PCB_VIA(self.b)
        vi.SetPosition(v(x, y))
        vi.SetDrill(MM(drill)); vi.SetWidth(MM(size))
        vi.SetViaType(P.VIATYPE_THROUGH)
        vi.SetLayerPair(layers[0] if layers[0] is not None else F_CU,
                        layers[1] if layers[1] is not None else B_CU)
        if net is not None: vi.SetNet(self.net(net) if isinstance(net, str) else net)
        self.b.Add(vi)
        return vi

    def via_stitch(self, pts, net="GND", **kw):
        for x, y in pts: self.via(x, y, net, **kw)

    # ------------------------------------------------------------------ zones
    def zone(self, pts, layers, net=None, priority=0, rule_area=False,
             name=None, thermal=False):
        z = P.ZONE(self.b)
        ls = P.LSET()
        for l in (layers if isinstance(layers, (list, tuple)) else [layers]):
            ls.addLayer(l)
        z.SetLayerSet(ls)
        if rule_area:
            # A plane SLIT, not a general keepout: copper pour is excluded so
            # the return current has to detour, but tracks, vias and pads are
            # still allowed through so the rest of the layout can cross it.
            z.SetIsRuleArea(True)
            z.SetDoNotAllowCopperPour(True)
            z.SetDoNotAllowTracks(False)
            z.SetDoNotAllowVias(False)
            z.SetDoNotAllowPads(False)
            z.SetDoNotAllowFootprints(False)
        elif net is not None:
            z.SetNet(self.net(net) if isinstance(net, str) else net)
        z.SetAssignedPriority(priority)
        if not rule_area:
            z.SetPadConnection(P.ZONE_CONNECTION_THERMAL if thermal
                               else P.ZONE_CONNECTION_FULL)
            z.SetLocalClearance(MM(0.25))
            z.SetMinThickness(MM(0.20))
        o = z.Outline()
        o.NewOutline()
        for x, y in pts:
            o.Append(MM(x), MM(y))
        if name: z.SetZoneName(name)
        self.b.Add(z)
        return z

    def rect_zone(self, x1, y1, x2, y2, *a, **kw):
        return self.zone([(x1, y1), (x2, y1), (x2, y2), (x1, y2)], *a, **kw)

    # --------------------------------------------------------- graphics / text
    def edge_rect(self, x1, y1, x2, y2, r=2.0):
        """Board outline with rounded corners, on Edge.Cuts."""
        segs = [((x1 + r, y1), (x2 - r, y1)), ((x2, y1 + r), (x2, y2 - r)),
                ((x2 - r, y2), (x1 + r, y2)), ((x1, y2 - r), (x1, y1 + r))]
        for a, b in segs:
            s = P.PCB_SHAPE(self.b); s.SetShape(P.SHAPE_T_SEGMENT)
            s.SetStart(v(*a)); s.SetEnd(v(*b))
            s.SetLayer(P.Edge_Cuts); s.SetWidth(MM(0.1)); self.b.Add(s)
        for cx, cy, a0 in ((x1 + r, y1 + r, 180), (x2 - r, y1 + r, 270),
                           (x2 - r, y2 - r, 0), (x1 + r, y2 - r, 90)):
            s = P.PCB_SHAPE(self.b); s.SetShape(P.SHAPE_T_ARC)
            import math
            p0 = (cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0)))
            p1 = (cx + r * math.cos(math.radians(a0 + 90)), cy + r * math.sin(math.radians(a0 + 90)))
            s.SetCenter(v(cx, cy)); s.SetStart(v(*p0)); s.SetEnd(v(*p1))
            s.SetLayer(P.Edge_Cuts); s.SetWidth(MM(0.1)); self.b.Add(s)

    def text(self, s, x, y, size=1.0, layer=None, thickness=0.15, rot=0,
             mirror=False, bold=False, just="left"):
        """Silkscreen text. Left-justified by default: KiCad centres text on
        its position, so a centred label placed 3 mm from the board edge runs
        off it, and DRC calls that "silkscreen clipped by board edge"."""
        t = P.PCB_TEXT(self.b)
        t.SetText(s); t.SetPosition(v(x, y))
        if just == "left":
            t.SetHorizJustify(P.GR_TEXT_H_ALIGN_LEFT)
        elif just == "right":
            t.SetHorizJustify(P.GR_TEXT_H_ALIGN_RIGHT)
        t.SetLayer(P.F_SilkS if layer is None else layer)
        t.SetTextSize(P.VECTOR2I(MM(size), MM(size)))
        t.SetTextThickness(MM(thickness))
        t.SetBold(bold)
        if rot: t.SetTextAngle(P.EDA_ANGLE(rot, P.DEGREES_T))
        if mirror: t.SetMirrored(True)
        self.b.Add(t)
        return t

    # ------------------------------------------------------- silkscreen placer
    def _silk_obstacles(self, layer):
        """Everything a new label must not touch: existing silkscreen, and the
        solder-mask openings, which is what DRC means by 'silkscreen clipped by
        solder mask'."""
        boxes = []
        for fp in self.b.Footprints():
            for it in list(fp.GraphicalItems()) + [fp.Reference(), fp.Value()]:
                visible = getattr(it, "IsVisible", lambda: True)()
                if visible and it.GetLayer() == layer:
                    boxes.append(it.GetBoundingBox())
            for pad in fp.Pads():
                if pad.IsOnLayer(P.F_Mask if layer == P.F_SilkS else P.B_Mask):
                    boxes.append(pad.GetBoundingBox())
        for it in self.b.Drawings():
            if it.GetLayer() == layer:
                boxes.append(it.GetBoundingBox())
        # a tented via has no mask opening, so silkscreen over it prints fine;
        # only an untented via is an obstacle
        ds = self.b.GetDesignSettings()
        tented = getattr(ds, "m_TentViasFront" if layer == P.F_SilkS else "m_TentViasBack", False)
        if not tented:
            for tr in self.b.GetTracks():
                if tr.Type() == P.PCB_VIA_T:
                    boxes.append(tr.GetBoundingBox())
        return boxes

    def label(self, s, candidates, size=0.85, layer=None, margin=0.3,
              bounds=None, preferred=None, **kw):
        """Place a silkscreen label at the first candidate position that is
        clear of everything already on the board.

        Hand-placing silkscreen on a board this dense is whack-a-mole: move one
        label off a pad and it lands on a reference designator. Giving each
        label a short list of acceptable positions and letting the generator
        pick turns that into a solved problem, and it stays solved when a part
        moves.
        """
        layer = P.F_SilkS if layer is None else layer
        boxes = self._silk_obstacles(layer)
        # The board edge is an obstacle too: DRC calls a label that runs off it
        # "silkscreen clipped by board edge".
        bx1, by1, bx2, by2 = bounds or (0.4, 0.4, self.w - 0.4, self.h - 0.4)
        preferred = len(candidates) if preferred is None else preferred
        for i, (x, y, rot) in enumerate(candidates):
            t = self.text(s, x, y, size=size, layer=layer, rot=rot, **kw)
            bb = t.GetBoundingBox()
            bb.Inflate(MM(margin))
            inside = (mm(bb.GetLeft()) >= bx1 and mm(bb.GetRight()) <= bx2
                      and mm(bb.GetTop()) >= by1 and mm(bb.GetBottom()) <= by2)
            if inside and not any(bb.Intersects(o) for o in boxes):
                if i >= preferred:
                    print(f"  silk: {s!r} fell back to ({mm(t.GetPosition().x):.1f}, "
                          f"{mm(t.GetPosition().y):.1f}) -- no room at its anchor")
                return t
            self.b.Remove(t)
        # say WHY the nearest candidate failed, or the fix is a guess
        x, y, rot = candidates[0]
        t = self.text(s, x, y, size=size, layer=layer, rot=rot, **kw)
        bb = t.GetBoundingBox()
        bb.Inflate(MM(margin))
        hits = [f"({mm(o.GetCenter().x):.1f},{mm(o.GetCenter().y):.1f})"
                for o in boxes if bb.Intersects(o)]
        self.b.Remove(t)
        raise SystemExit(f"no free silkscreen position for {s!r} "
                         f"({len(candidates)} candidates tried); at ({x:.1f},{y:.1f}) "
                         f"it hits {len(hits)} obstacles near {hits[:6]}, text box "
                         f"{mm(bb.GetLeft()):.1f}..{mm(bb.GetRight()):.1f} x "
                         f"{mm(bb.GetTop()):.1f}..{mm(bb.GetBottom()):.1f}")

    def line(self, p1, p2, layer=None, width=0.15):
        s = P.PCB_SHAPE(self.b); s.SetShape(P.SHAPE_T_SEGMENT)
        s.SetStart(v(*p1)); s.SetEnd(v(*p2))
        s.SetLayer(P.F_SilkS if layer is None else layer)
        s.SetWidth(MM(width)); self.b.Add(s)
        return s

    # ------------------------------------------------------------------ output
    def fill(self, clearance=0.25, max_error=0.005, clearance_of=None):
        """Fill the copper pours.

        pcbnew's own ZONE_FILLER reaches into wxWidgets and segfaults the
        interpreter when there is no GUI, so the fill is computed here with the
        same polygon operations it would use: start from the zone outline,
        subtract every piece of copper that is NOT on the zone's net (inflated
        by the clearance), subtract the rule areas and the footprints' own
        keepouts, then deflate-and-reinflate to drop slivers thinner than the
        zone's minimum thickness.

        Doing this matters beyond tidiness. kicad-cli does not refill before
        DRC, so on an unfilled board every pad that depends on a pour -- which
        here is every ground pad on both sides of the barrier -- is reported as
        an unconnected item, and the real violations are lost in the noise.
        """
        CL, ME = MM(clearance), MM(max_error)
        # Anchors: every point where a copper item of a given net actually
        # touches the board. A filled island containing none of them is
        # connected to nothing, which is what "remove islands" means.
        self._anchors = {}
        for fp in self.b.Footprints():
            for pad in fp.Pads():
                self._anchors.setdefault(pad.GetNetCode(), []).append(
                    (pad.GetPosition(), pad.GetLayerSet()))
        for tr in self.b.GetTracks():
            ls = tr.GetLayerSet()
            for pt in (tr.GetStart(), tr.GetEnd()):
                self._anchors.setdefault(tr.GetNetCode(), []).append((pt, ls))
        keepouts = []
        for z in list(self.b.Zones()) + [z for f in self.b.Footprints() for z in f.Zones()]:
            if z.GetIsRuleArea() and z.GetDoNotAllowCopperPour():
                keepouts.append(z)

        filled = 0
        self._fills = []
        for z in self.b.Zones():
            if z.GetIsRuleArea():
                continue
            znet = z.GetNetCode()
            for layer in z.GetLayerSet().Seq():
                poly = P.SHAPE_POLY_SET(z.Outline())
                poly.Deflate(z.GetMinThickness() // 2, P.CORNER_STRATEGY_ROUND_ALL_CORNERS, ME)

                cut = P.SHAPE_POLY_SET()
                for fp in self.b.Footprints():
                    for pad in fp.Pads():
                        if pad.GetNetCode() == znet or not pad.IsOnLayer(layer):
                            continue
                        pad.TransformShapeToPolygon(cut, layer, self._cl(pad, CL, clearance_of),
                                                    ME, P.ERROR_OUTSIDE)
                for tr in self.b.GetTracks():
                    if tr.GetNetCode() == znet or not tr.IsOnLayer(layer):
                        continue
                    tr.TransformShapeToPolygon(cut, layer, self._cl(tr, CL, clearance_of),
                                               ME, P.ERROR_OUTSIDE)
                for k in keepouts:
                    if k.GetLayerSet().Contains(layer):
                        ko = P.SHAPE_POLY_SET(k.Outline())
                        cut.BooleanAdd(ko)

                cut.Simplify()
                poly.BooleanSubtract(cut)
                poly.Simplify()
                # drop anything narrower than the zone's minimum thickness FIRST:
                # thinning can cut one region in two, and an island test run
                # before it keeps a piece that no longer touches its anchor
                half = z.GetMinThickness() // 2
                poly.Deflate(half, P.CORNER_STRATEGY_ROUND_ALL_CORNERS, ME)
                poly.Inflate(half, P.CORNER_STRATEGY_ROUND_ALL_CORNERS, ME)
                poly.Simplify()
                self._drop_islands(poly, znet, layer)
                self._fills.append((z, layer, poly))
            z.SetIsFilled(True)
            z.SetNeedRefill(False)
        self.stranded = self._keep_connected()
        for z, layer, poly in self._fills:
            poly.Fracture()
            z.SetFilledPolysList(layer, poly)
            filled += 1
        return filled

    def _keep_connected(self):
        """Keep only the pour that is actually joined to the net's pads.

        An island that touches a via is not "connected" if the via lands in a
        back-layer island that touches nothing else -- KiCad reports both as
        unconnected items. So every island, pad, via and track of each pour
        net goes into a union-find, joined wherever one contains the other's
        anchor point, and only the component holding the most pads survives.
        Returns the items of that net that did not make it, by description.
        """
        stranded = []
        nets = {z.GetNetCode() for z, _, _ in self._fills}
        for net in nets:
            parent = {}

            def find(a):
                parent.setdefault(a, a)
                while parent[a] != a:
                    parent[a] = parent[parent[a]]
                    a = parent[a]
                return a

            def union(a, b):
                parent[find(a)] = find(b)

            pads = [(f"{fp.GetReference()}.{pd.GetNumber()}", pd) for fp in self.b.Footprints()
                    for pd in fp.Pads() if pd.GetNetCode() == net]
            tracks = [t for t in self.b.GetTracks() if t.GetNetCode() == net]
            islands = []
            for zi, (z, layer, poly) in enumerate(self._fills):
                if z.GetNetCode() != net:
                    continue
                for i in range(poly.OutlineCount()):
                    islands.append((("Z", zi, i), layer, poly, i))
            for name, pd in pads:
                find(("P", name))
                for key, layer, poly, i in islands:
                    if pd.IsOnLayer(layer) and poly.Contains(pd.GetPosition(), i):
                        union(("P", name), key)
            for k, t in enumerate(tracks):
                node = ("T", k)
                find(node)
                pts = [t.GetPosition()] if t.Type() == P.PCB_VIA_T else [t.GetStart(), t.GetEnd()]
                for key, layer, poly, i in islands:
                    if t.IsOnLayer(layer) and any(poly.Contains(q, i) for q in pts):
                        union(node, key)
                for name, pd in pads:
                    if any(pd.HitTest(q) for q in pts):
                        union(node, ("P", name))
                for k2, t2 in enumerate(tracks[:k]):
                    q2 = [t2.GetPosition()] if t2.Type() == P.PCB_VIA_T else [t2.GetStart(), t2.GetEnd()]
                    if any(a == c for a in pts for c in q2):
                        union(node, ("T", k2))
            count = {}
            for name, _ in pads:
                r = find(("P", name))
                count[r] = count.get(r, 0) + 1
            if not count:
                continue
            main = max(count, key=count.get)
            for key, layer, poly, i in sorted(islands, key=lambda it: -it[3]):
                if find(key) != main:
                    poly.DeletePolygon(i)
            stranded += [name for name, _ in pads if find(("P", name)) != main]
        return stranded

    @staticmethod
    def _cl(item, default, clearance_of):
        """Pour clearance to an item: the larger of the pour's and the item's
        net-class clearance. A single number for every net would either let the
        ground pour crowd the 24 V nets or starve the logic of ground."""
        if clearance_of is None:
            return default
        name = item.GetNetname()
        return max(default, MM(clearance_of(name)) if name else default)

    def _drop_islands(self, poly, netcode, layer):
        """Delete filled regions that touch nothing on the zone's net.

        KiCad calls this island removal and does it by default. Without it a
        pour leaves slivers of floating copper -- harmless in most places,
        and exactly what you do not want beside an isolation barrier.
        """
        anchors = [pt for pt, ls in self._anchors.get(netcode, []) if ls.Contains(layer)]
        for i in range(poly.OutlineCount() - 1, -1, -1):
            if not any(poly.Contains(pt, i) for pt in anchors):
                poly.DeletePolygon(i)

    def save(self, path):
        self.b.SetFileName(path)
        P.SaveBoard(path, self.b)
        return path
