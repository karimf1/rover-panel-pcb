#!/usr/bin/env python3
"""Write lib/rover-panel-supervisor.kicad_sym -- the one symbol KiCad's stock
libraries do not have.

KiCad 9 ships 74LVC1G79 (a D flip-flop with no set or clear) but not the
74LVC1G74.  The interlock needs the clear: /CLR is how an open E-stop or a
dropped ARM takes EN down *immediately*, independent of the clock, and the
clock edge is how a released E-stop is prevented from re-energising K1 by
itself.  So the symbol is drawn here, from the SN74LVC1G74 DCT (SSOP-8) pin
map, and generated rather than hand-edited so its pin numbers live in one
place: spec.U5_PINOUT.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "design")))
import spec as S  # noqa: E402

NAME = "SN74LVC1G74DCT"
FP = "Package_SO:SSOP-8_2.95x2.8mm_P0.65mm"


def font(hide=False):
    h = "\n\t\t\t\t(hide yes)" if hide else ""
    return f"(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t){h}\n\t\t\t)"


def prop(k, v, x, y, hide=False):
    return (f'\t\t(property "{k}" "{v}"\n\t\t\t(at {x} {y} 0)\n'
            f'\t\t\t{font(hide)}\n\t\t)')


def pin(etype, shape, x, y, rot, name, num, length=5.08):
    return (f'\t\t\t(pin {etype} {shape}\n\t\t\t\t(at {x} {y} {rot})\n'
            f'\t\t\t\t(length {length})\n'
            f'\t\t\t\t(name "{name}"\n\t\t\t\t\t{font()}\n\t\t\t\t)\n'
            f'\t\t\t\t(number "{num}"\n\t\t\t\t\t{font()}\n\t\t\t\t)\n\t\t\t)')


P = S.U5_PINOUT
PINS = [
    # etype        shape       x       y     rot  name       number
    ("input",       "line",   -12.7,  2.54,   0, "D",       P["D"]),
    ("input",       "clock",  -12.7, -2.54,   0, "CLK",     P["CLK"]),
    ("input",       "line",    0.0,  12.7,  270, "~{PRE}",  P["~PRE"]),
    ("input",       "line",    0.0, -12.7,   90, "~{CLR}",  P["~CLR"]),
    ("output",      "line",   12.7,  2.54,  180, "Q",       P["Q"]),
    ("output",      "line",   12.7, -2.54,  180, "~{Q}",    P["~Q"]),
    ("power_in",    "line",   -5.08, 12.7,  270, "VCC",     P["VCC"]),
    ("power_in",    "line",   -5.08, -12.7,  90, "GND",     P["GND"]),
]


def symbol():
    body = (f'\t\t(symbol "{NAME}_0_1"\n\t\t\t(rectangle\n\t\t\t\t(start -7.62 7.62)\n'
            f'\t\t\t\t(end 7.62 -7.62)\n\t\t\t\t(stroke\n\t\t\t\t\t(width 0.254)\n'
            f'\t\t\t\t\t(type default)\n\t\t\t\t)\n\t\t\t\t(fill\n\t\t\t\t\t(type background)\n'
            f'\t\t\t\t)\n\t\t\t)\n\t\t)')
    pins = "\n".join(pin(*p) for p in PINS)
    return "\n".join([
        f'\t(symbol "{NAME}"',
        "\t\t(pin_names\n\t\t\t(offset 1.016)\n\t\t)",
        "\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)",
        prop("Reference", "U", -7.62, 10.16),
        prop("Value", NAME, 2.54, 10.16),
        prop("Footprint", FP, 0, -15.24, True),
        prop("Datasheet", "https://www.ti.com/lit/ds/symlink/sn74lvc1g74.pdf", 0, 0, True),
        prop("Description", "Single positive-edge D flip-flop with asynchronous "
             "active-low preset and clear, 1.65-5.5 V, SSOP-8 (DCT)", 0, 0, True),
        prop("MPN", "SN74LVC1G74DCTR", 0, 0, True),
        prop("Manufacturer", "Texas Instruments", 0, 0, True),
        prop("ki_keywords", "flip-flop D clear preset LVC", 0, 0, True),
        body,
        f'\t\t(symbol "{NAME}_1_1"\n{pins}\n\t\t)',
        "\t\t(embedded_fonts no)",
        "\t)",
    ])


if __name__ == "__main__":
    out = os.path.normpath(os.path.join(HERE, "..", "lib", "rover-panel-supervisor.kicad_sym"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write(
        '(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "rps-gen")\n'
        '\t(generator_version "9.0")\n' + symbol() + "\n)\n")
    print("wrote", out)
