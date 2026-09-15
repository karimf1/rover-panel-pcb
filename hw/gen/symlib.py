"""Pull symbols out of KiCad's stock libraries, resolve (extends ...), and
emit flat blocks suitable for a schematic's `lib_symbols` section.

A schematic embeds a full copy of every symbol it uses, so a project generated
this way opens correctly on a machine whose stock libraries differ from ours.
"""
import os, sys, copy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sexp

LIBDIRS = [
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols",
    "/usr/share/kicad/symbols",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"),
]

_cache = {}

def _libpath(lib):
    for d in LIBDIRS:
        p = os.path.join(d, lib + ".kicad_sym")
        if os.path.exists(p): return p
    raise FileNotFoundError("symbol library not found: " + lib)

def load(lib):
    if lib not in _cache:
        top = sexp.parse(open(_libpath(lib)).read())
        _cache[lib] = {s[1]: s for s in sexp.findall(top, "symbol")}
    return _cache[lib]

def flat(lib, name):
    """Flattened symbol node, renamed to "lib:name", extends resolved."""
    syms = load(lib)
    if name not in syms:
        raise KeyError("%s not in %s (have: %s...)" % (name, lib, sorted(syms)[:5]))
    blk = copy.deepcopy(syms[name])
    ext = sexp.find(blk, "extends")
    if ext:
        parent = copy.deepcopy(syms[ext[1]])
        pname = ext[1]
        # child properties win; parent supplies graphics, pins and flags
        child_props = {p[1]: p for p in sexp.findall(blk, "property")}
        out = [c for c in parent if not (isinstance(c, list) and c[0] in ("property", "symbol"))]
        for p in sexp.findall(parent, "property"):
            out.append(child_props.pop(p[1], p))
        for p in child_props.values():
            out.append(p)
        for unit in sexp.findall(parent, "symbol"):
            u = copy.deepcopy(unit)
            u[1] = sexp.QStr(str(u[1]).replace(pname, name, 1))
            out.append(u)
        blk = out
        blk[0] = "symbol"
    blk[1] = sexp.QStr("%s:%s" % (lib, name))
    # strip tokens a schematic's lib_symbols does not carry
    return [c for c in blk if not (isinstance(c, list) and c[0] == "extends")]

def pins(lib, name):
    """[(number, name, etype, x, y, rot, length)] in symbol-local coordinates."""
    out = []
    for unit in sexp.findall(flat(lib, name), "symbol"):
        for p in sexp.findall(unit, "pin"):
            at = sexp.find(p, "at")
            out.append((
                str(sexp.val(sexp.find(p, "number"), "number", 1, "?")
                    if False else sexp.find(p, "number")[1]),
                str(sexp.find(p, "name")[1]),
                str(p[1]),
                float(at[1]), float(at[2]), int(float(at[3])) if len(at) > 3 else 0,
                float(sexp.find(p, "length")[1]),
            ))
    return out

def pin_units(lib, name):
    """number -> unit (0 = common to every unit), read from the sub-symbol
    names, which KiCad spells NAME_<unit>_<body style>."""
    out = {}
    for unit in sexp.findall(flat(lib, name), "symbol"):
        u = int(str(unit[1]).rsplit("_", 2)[-2])
        for p in sexp.findall(unit, "pin"):
            out[str(sexp.find(p, "number")[1])] = u
    return out


def pinmap(lib, name):
    """number -> (x, y) connection point in symbol-local coordinates."""
    return {p[0]: (p[3], p[4]) for p in pins(lib, name)}

if __name__ == "__main__":
    lib, name = sys.argv[1], sys.argv[2]
    for num, nm, et, x, y, rot, ln in pins(lib, name):
        print(f"  pin {num:>3}  {nm:<12} {et:<14} at ({x:7.2f},{y:7.2f}) rot {rot:3d} len {ln}")
