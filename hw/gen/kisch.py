"""Emit a KiCad 9 .kicad_sch file.

Small builder: you add symbols, wires, labels and power flags at explicit
coordinates and it writes the S-expression. Pin connection points are computed
from the real symbol geometry (see symlib), so a wire that ends on a pin's
coordinate genuinely connects to it.
"""
import os, sys, uuid as _uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import symlib, sexp

VERSION = "20250114"
GEN_VER = "9.0"


def uid(seed=None):
    """Deterministic UUIDs: regenerating the schematic yields a clean diff."""
    if seed is None:
        return str(_uuid.uuid4())
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, "rover-panel-supervisor/" + str(seed)))


def pin_xy(lib, name, number, x, y, rot=0, mirror=None):
    """Sheet coordinate of a pin for a symbol placed at (x, y) with rotation.

    Symbol space has +Y up; the sheet has +Y down. KiCad applies the mirror
    first, then the rotation, then the Y flip.
    """
    px, py = symlib.pinmap(lib, name)[str(number)]
    if mirror == "x":  py = -py
    elif mirror == "y": px = -px
    # Screen coords at rotation 0 are (px, -py); KiCad then rotates the symbol
    # counter-clockwise on screen, which in this Y-down frame is
    # (u, v) -> (u cos + v sin, -u sin + v cos). Verified against kicad-cli's
    # own netlister for all four rotations -- see hw/gen/test_kisch.py (sync-buck).
    r = rot % 360
    if   r == 0:   dx, dy = px, -py
    elif r == 90:  dx, dy = -py, -px
    elif r == 180: dx, dy = -px, py
    elif r == 270: dx, dy = py, px
    else: raise ValueError("rotation must be a multiple of 90")
    return (round(x + dx, 4), round(y + dy, 4))


class Sch:
    def __init__(self, project, title="", rev="", company="", paper="A3"):
        self.project = project
        self.paper = paper
        self.title, self.rev, self.company = title, rev, company
        self.root_uuid = uid("root")
        self.items = []          # rendered strings
        self.used = {}           # lib_id -> flattened symbol node
        self.comments = []

    # ------------------------------------------------------------------ pieces
    def wire(self, x1, y1, x2, y2):
        self.items.append(
            f'\t(wire\n\t\t(pts\n\t\t\t(xy {x1} {y1}) (xy {x2} {y2})\n\t\t)\n'
            f'\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
            f'\t\t(uuid "{uid(f"w{x1},{y1},{x2},{y2}")}")\n\t)')
        return self

    def poly(self, pts):
        for a, b in zip(pts, pts[1:]):
            self.wire(a[0], a[1], b[0], b[1])
        return self

    def rail(self, fixed, taps, horizontal=True, junctions=True):
        """A rail with components tapping off it along its length.

        KiCad only connects a pin to a wire at a wire ENDPOINT (or at a lone
        junction). A single long wire with several junctions on it connects
        only the first tap -- verified against kicad-cli, see
        hw/gen/test_kisch.py (sync-buck). So a rail is emitted as one segment between each
        consecutive pair of taps, which puts every tap on an endpoint.
        """
        ts = sorted(set(round(t, 4) for t in taps))
        for a, b in zip(ts, ts[1:]):
            self.wire(a, fixed, b, fixed) if horizontal else self.wire(fixed, a, fixed, b)
        if junctions:
            for t in ts[1:-1]:
                self.junction(t, fixed) if horizontal else self.junction(fixed, t)
        return self

    def junction(self, x, y):
        self.items.append(
            f'\t(junction\n\t\t(at {x} {y})\n\t\t(diameter 0)\n'
            f'\t\t(color 0 0 0 0)\n\t\t(uuid "{uid(f"j{x},{y}")}")\n\t)')
        return self

    def label(self, text, x, y, rot=0, justify="left bottom"):
        self.items.append(
            f'\t(label "{text}"\n\t\t(at {x} {y} {rot})\n\t\t(effects\n'
            f'\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            f'\t\t\t(justify {justify})\n\t\t)\n'
            f'\t\t(uuid "{uid(f"l{text}{x},{y}")}")\n\t)')
        return self

    def text(self, s, x, y, size=1.27, rot=0):
        esc = s.replace('\\', '\\\\').replace('"', '\\"')
        self.items.append(
            f'\t(text "{esc}"\n\t\t(exclude_from_sim no)\n\t\t(at {x} {y} {rot})\n'
            f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size {size} {size})\n\t\t\t)\n'
            f'\t\t\t(justify left bottom)\n\t\t)\n'
            f'\t\t(uuid "{uid(f"t{s}{x},{y}")}")\n\t)')
        return self

    def rect(self, x1, y1, x2, y2, width=0.2, fill="none"):
        self.items.append(
            f'\t(rectangle\n\t\t(start {x1} {y1})\n\t\t(end {x2} {y2})\n'
            f'\t\t(stroke\n\t\t\t(width {width})\n\t\t\t(type dash)\n\t\t)\n'
            f'\t\t(fill\n\t\t\t(type {fill})\n\t\t)\n'
            f'\t\t(uuid "{uid(f"r{x1},{y1},{x2},{y2}")}")\n\t)')
        return self

    def no_connect(self, x, y):
        self.items.append(
            f'\t(no_connect\n\t\t(at {x} {y})\n\t\t(uuid "{uid(f"nc{x},{y}")}")\n\t)')
        return self

    # ----------------------------------------------------------------- symbols
    def sym(self, lib, name, ref, x, y, rot=0, value=None, footprint=None,
            fields=(), dnp=False, hide_ref=False, hide_value=False,
            ref_dy=-7.62, val_dy=7.62, mirror=None, unit=1, in_bom=True):
        lib_id = f"{lib}:{name}"
        if lib_id not in self.used:
            self.used[lib_id] = symlib.flat(lib, name)
        value = name if value is None else value
        props = []
        # Field angles are absolute on the sheet, but KiCad draws a field on a
        # 90/270-degree symbol rotated with it unless the field says otherwise.
        # Giving it the symbol's own angle keeps every reference and value
        # reading left to right.
        fang = rot % 180

        def prop(k, v, px, py, hide, just=None):
            h = "\n\t\t\t\t(hide yes)" if hide else ""
            j = f"\n\t\t\t(justify {just})" if just else ""
            props.append(
                f'\t\t(property "{k}" "{v}"\n\t\t\t(at {px} {py} {fang})\n'
                f'\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t){h}\n\t\t\t){j}\n\t\t)')
        prop("Reference", ref, x, round(y + ref_dy, 4), hide_ref)
        prop("Value", value, x, round(y + val_dy, 4), hide_value)
        prop("Footprint", footprint or "", x, y, True)
        prop("Datasheet", "~", x, y, True)
        prop("Description", "", x, y, True)
        for i, (k, v) in enumerate(fields):
            prop(k, v, x, round(y + val_dy + 2.54 * (i + 1), 4), True)
        # A multi-unit part (the LM339 is four comparators and a power unit in
        # one package) is placed once per unit under the same reference. Each
        # placement lists only its own pins, and its UUIDs are seeded with the
        # unit, or every unit would claim the same symbol and pin identities.
        units = symlib.pin_units(lib, name)
        multi = len({u for u in units.values() if u}) > 1
        useed = "" if unit == 1 else f"u{unit}"
        pin_lines = "\n".join(
            f'\t\t(pin "{p[0]}"\n\t\t\t(uuid "{uid(f"{ref}{useed}p{p[0]}")}")\n\t\t)'
            for p in symlib.pins(lib, name)
            if not multi or units.get(p[0]) in (0, unit))
        mir = f"\n\t\t(mirror {mirror})" if mirror else ""
        self.items.append(
            f'\t(symbol\n\t\t(lib_id "{lib_id}")\n\t\t(at {x} {y} {rot}){mir}\n'
            f'\t\t(unit {unit})\n\t\t(exclude_from_sim no)\n\t\t(in_bom {"yes" if in_bom else "no"})\n'
            f'\t\t(on_board yes)\n\t\t(dnp {"yes" if dnp else "no"})\n'
            f'\t\t(uuid "{uid("s" + ref + useed)}")\n' + "\n".join(props) + "\n" + pin_lines + "\n"
            f'\t\t(instances\n\t\t\t(project "{self.project}"\n'
            f'\t\t\t\t(path "/{self.root_uuid}"\n\t\t\t\t\t(reference "{ref}")\n'
            f'\t\t\t\t\t(unit {unit})\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)')
        return pin_xy_factory(lib, name, x, y, rot, mirror)

    def gnd(self, x, y, ref=None):
        """power:GND with its pin at (x, y). Symbol draws downward."""
        self.sym("power", "GND", ref or f"#PWR{uid(f'g{x},{y}')[:6]}", x, round(y + 0, 4),
                 value="GND", hide_ref=True, hide_value=True, ref_dy=-3.81,
                 val_dy=3.81, in_bom=False)
        return self

    def pwr_flag(self, x, y, ref=None):
        self.sym("power", "PWR_FLAG", ref or f"#FLG{uid(f'f{x},{y}')[:6]}", x, y,
                 value="PWR_FLAG", hide_ref=True, hide_value=True, in_bom=False)
        return self

    # ------------------------------------------------------------------ output
    def render(self):
        libs = "\n".join(sexp.dump(self.used[k], 2) for k in sorted(self.used))
        tb = ""
        if self.title or self.rev or self.company or self.comments:
            lines = [f'\t\t(title "{self.title}")' if self.title else "",
                     f'\t\t(rev "{self.rev}")' if self.rev else "",
                     f'\t\t(company "{self.company}")' if self.company else ""]
            for i, c in enumerate(self.comments, 1):
                lines.append(f'\t\t(comment {i} "{c}")')
            tb = "\t(title_block\n" + "\n".join(l for l in lines if l) + "\n\t)\n"
        return (f'(kicad_sch\n\t(version {VERSION})\n\t(generator "rps-gen")\n'
                f'\t(generator_version "{GEN_VER}")\n\t(uuid "{self.root_uuid}")\n'
                f'\t(paper "{self.paper}")\n' + tb +
                f'\t(lib_symbols\n{libs}\n\t)\n' + "\n".join(self.items) +
                f'\n\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n'
                f'\t(embedded_fonts no)\n)\n')

    def write(self, path):
        open(path, "w").write(self.render())
        return path


def pin_xy_factory(lib, name, x, y, rot, mirror):
    """Returns a callable p(number) -> (sheet_x, sheet_y) for this placement."""
    def p(number):
        return pin_xy(lib, name, number, x, y, rot, mirror)
    p.lib, p.name, p.at, p.rot = lib, name, (x, y), rot
    return p
