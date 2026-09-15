#!/usr/bin/env python3
"""The board's one claim, checked against the netlist KiCad exported.

    K1 cannot close unless the E-stop loop is closed AND the host has raised a
    fresh ARM edge AND the switched bus has reached the precharge threshold.

design/test_calcs.py simulates that behaviour from the thresholds. This script
checks the STRUCTURE that the simulation assumes: that the copper really is
wired the way the simulation says, so that no part on the board -- through a
wrong net, a swapped pin, a stray resistor -- can energise the coil any other
way. It reads rover-panel-supervisor.net, not the generator, so it checks what
KiCad will build rather than what the generator meant.

Every check names the specific parts it is about. Exit status 0 only if all pass.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NET = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "rover-panel-supervisor.net")

FAILED = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  -- ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


# ------------------------------------------------------------------ netlist
text = open(NET).read()
COMP = {}
for m in re.finditer(r'\(comp \(ref "([^"]+)"\)\s*\(value "([^"]*)"\)[\s\S]*?'
                     r'\(libsource \(lib "([^"]*)"\) \(part "([^"]*)"\)', text):
    COMP[m.group(1)] = dict(value=m.group(2), lib=m.group(3), part=m.group(4))
NETS = {}
PIN = {}                       # (ref, pin) -> net
for m in re.finditer(r'\(net \(code "\d+"\) \(name "([^"]*)"\)[^\n]*\n((?:\s+\(node[^\n]*\n?)*)',
                     text[text.index("(nets"):]):
    name = m.group(1).lstrip("/")
    nodes = re.findall(r'\(ref "([^"]+)"\) \(pin "([^"]+)"\)', m.group(2))
    NETS[name] = nodes
    for r, p in nodes:
        PIN[(r, p)] = name


def ohms(v):
    """'9k76 0.1%' -> 9760.0; None if it is not a resistance."""
    m = re.match(r"^(\d+)([RkM])(\d*)", v)
    if not m:
        return None
    mult = {"R": 1, "k": 1e3, "M": 1e6}[m.group(2)]
    return float(f"{m.group(1)}.{m.group(3) or 0}") * mult


def on(net):
    return NETS.get(net, [])


def kind(ref):
    p = COMP[ref]["part"]
    if ref.startswith("R"):
        return "R"
    if ref.startswith("C"):
        return "C"
    if ref.startswith("TP"):
        return "TP"
    if ref.startswith("P"):
        return "CONN"
    if p in ("2N7002", "NDT3055L"):
        return "NFET"
    if p == "Q_PMOS_GDS":
        return "PFET"
    if p.startswith("SM6T") or p == "D_TVS":
        return "TVS"
    if ref.startswith("D"):
        return "D"
    if ref.startswith("L"):
        return "L"
    return "IC"


# FET pins: 2N7002 is G=1 S=2 D=3; NDT3055L and Q_PMOS_GDS are G=1 D=2 S=3
def fet_pins(ref):
    if COMP[ref]["part"] == "2N7002":
        return {"G": "1", "S": "2", "D": "3"}
    return {"G": "1", "D": "2", "S": "3"}


print("== interlock: structural checks on the exported netlist ==")
print(f"  {len(COMP)} parts, {len(NETS)} nets")

# --------------------------------------------------- 1. the E-stop loop is the
# only way pack voltage reaches the coil's positive side
LOW_OHM = 1000.0


def conducting_neighbours(net):
    """Nets reachable from `net` through one part that could carry coil current:
    a resistor under 1 k, an inductor, any diode forward or zener, and EVERY
    FET channel as if it were switched on. TVS parts count as open -- they
    stand off above a full pack, which spec.py checks."""
    out = set()
    for ref, pin in on(net):
        k = kind(ref)
        pins = [p for (r, p) in PIN if r == ref]
        others = {PIN[(ref, p)] for p in pins if p != pin}
        if k == "R" and (ohms(COMP[ref]["value"]) or 0) < LOW_OHM:
            out |= others
        elif k in ("L", "D"):
            out |= others
        elif k in ("NFET", "PFET"):
            fp = fet_pins(ref)
            if pin in (fp["D"], fp["S"]):
                out.add(PIN[(ref, fp["S"] if pin == fp["D"] else fp["D"])])
    return out


seen, todo = {"+24V_IN"}, ["+24V_IN"]
while todo:
    n = todo.pop()
    for m in conducting_neighbours(n):
        if m not in seen and m != "GND":
            seen.add(m)
            todo.append(m)
check("no on-board path from +24V_IN to COIL_POS, even with every FET on",
      "COIL_POS" not in seen,
      f"+24V_IN reaches {len(seen)} nets through low-impedance parts; COIL_POS is not one")

coil_pos_parts = sorted({r for r, _ in on("COIL_POS")})
ok = True
why = []
for r in coil_pos_parts:
    k = kind(r)
    if k == "CONN":
        continue
    if k == "TVS":
        other = [PIN[(r, p)] for (rr, p) in PIN if rr == r and PIN[(rr, p)] != "COIL_POS"]
        ok &= other == ["GND"]
        why.append(f"{r} TVS to {other}")
    elif k == "R":
        ok &= (ohms(COMP[r]["value"]) or 0) >= 100e3
        why.append(f"{r} {COMP[r]['value']}")
    else:
        ok = False
        why.append(f"{r} UNEXPECTED")
check("COIL_POS touches only P1, a clamp to GND and a >= 100 k sense resistor",
      ok, ", ".join(why))
check("COIL_POS arrives on two P1 pins: E-stop return in, coil + out",
      sorted(p for r, p in on("COIL_POS") if r == "P1") == ["3", "4"])
check("the E-stop loop source is +24V_IN on P1.8",
      PIN.get(("P1", "8")) == "+24V_IN")

# ------------------------------------------------ 2. the coil's low side
cn = sorted(on("COIL_NEG"))
q1 = fet_pins("Q1")
check("COIL_NEG goes only to P1.6, Q1's drain and a clamp",
      set(cn) == {("P1", "6"), ("Q1", q1["D"]), ("D5", "1")}, str(cn))
check("Q1's source is GND", PIN[("Q1", q1["S"])] == "GND")
check("Q1's gate is driven only through R30 from K1_G (R31 pulls it down)",
      sorted(r for r, _ in on(PIN[("Q1", q1["G"])])) == ["Q1", "R30", "R31"]
      and {PIN[("R30", "1")], PIN[("R30", "2")]} == {"K1_G", "Q1_G"}
      and {PIN[("R31", "1")], PIN[("R31", "2")]} == {"Q1_G", "GND"})

# ------------------------------------------------ 3. what can pull K1_G high
pullers, holders, loads = [], [], []
for r, p in on("K1_G"):
    k = kind(r)
    if k == "R":
        other = PIN[(r, "2" if p == "1" else "1")]
        (pullers if other not in ("GND", "Q1_G") else loads).append(f"{r}->{other}")
    elif k == "NFET":
        fp = fet_pins(r)
        if p == fp["D"]:
            assert PIN[(r, fp["S"])] == "GND", r
            holders.append(f"{r}(gate {PIN[(r, fp['G'])]})")
        else:
            loads.append(f"{r} gate")
    elif k in ("C", "TP"):
        loads.append(r)
    else:
        pullers.append(f"{r} UNEXPECTED")
check("the ONLY thing that can raise K1_G is one resistor from EN",
      pullers == ["R29->EN"], f"pull-ups {pullers}")
check("K1_G is held low by precharge-in-progress (CHG) and by FAULT",
      sorted(h.split("gate ")[1].rstrip(")") for h in holders) == ["CHG", "FAULT"],
      ", ".join(holders))

# ------------------------------------------------ 4. EN is the latch output
drv = [(r, p) for r, p in on("EN") if kind(r) not in ("R", "TP")]
check("EN is driven by U5.Q (pin 5) and nothing else", drv == [("U5", "5")], str(drv))
check("everything else on EN is a pull-up it feeds",
      all(kind(r) in ("R", "TP") for r, _ in on("EN") if (r, _) != ("U5", "5")))
check("U5 D and /PRE are tied high: it can only SET on a clock edge",
      PIN[("U5", "2")] == "+5V" and PIN[("U5", "7")] == "+5V")
check("U5 /CLR = U4 output = ARM AND ESTOP_OK",
      PIN[("U5", "6")] == "CLR_N" and sorted(on("CLR_N")) == [("U4", "4"), ("U5", "6")]
      and {PIN[("U4", "1")], PIN[("U4", "2")]} == {"ARM", "ESTOP_OK"})
check("U5 is clocked by ARM delayed through R28/C17",
      PIN[("U5", "1")] == "ARM_DLY"
      and {PIN[("R28", "1")], PIN[("R28", "2")]} == {"ARM", "ARM_DLY"})

# ------------------------------------------------ 5. the comparators read what they claim
# LM339 SOIC-14:  A (+5 -4 out 2)  B (+7 -6 out 1)  C (+11 -10 out 13)  D (+9 -8 out 14)
check("ESTOP_OK compares VE (+11) against VREF (-10) on output 13",
      (PIN[("U3", "13")], PIN[("U3", "11")], PIN[("U3", "10")]) == ("ESTOP_OK", "VE", "VREF"))
check("VE is a divider off COIL_POS -- the FAR side of the E-stop loop",
      {PIN[("R18", "1")], PIN[("R18", "2")]} == {"COIL_POS", "VE"}
      and {PIN[("R19", "1")], PIN[("R19", "2")]} == {"VE", "GND"})
check("CHG compares VA (+5, always-on bus) against VS (-4, switched bus) on output 2",
      (PIN[("U3", "2")], PIN[("U3", "5")], PIN[("U3", "4")]) == ("CHG", "VA", "VS"))
check("VA divides +24V_IN and VS divides SW_SENSE",
      {PIN[("R12", "1")], PIN[("R12", "2")]} == {"+24V_IN", "VA"}
      and {PIN[("R14", "1")], PIN[("R14", "2")]} == {"SW_SENSE", "VS"})
check("SW_SENSE comes in on P1.9 and PRE_OUT leaves on P1.10",
      PIN[("P1", "9")] == "SW_SENSE" and PIN[("P1", "10")] == "PRE_OUT")
check("FAULT is the timer comparator (TMR +7 vs VREF_T -6, output 1)",
      (PIN[("U3", "1")], PIN[("U3", "7")], PIN[("U3", "6")]) == ("FAULT", "TMR", "VREF_T"))
check("ARM is the receiver comparator (VARM +9 vs VREF -8, output 14)",
      (PIN[("U3", "14")], PIN[("U3", "9")], PIN[("U3", "8")]) == ("ARM", "VARM", "VREF"))
check("an unplugged harness reads as disarmed (R22 pulls VARM to GND)",
      {PIN[("R22", "1")], PIN[("R22", "2")]} == {"VARM", "GND"})

# ------------------------------------------------ 6. the precharge switch
q6 = fet_pins("Q6")
check("Q6 switches +24V_IN to PRE_OUT",
      PIN[("Q6", q6["S"])] == "+24V_IN" and PIN[("Q6", q6["D"])] == "PRE_OUT")
pg_up = [r for r, p in on("PRE_G") if kind(r) == "R"]
check("PRE_G is raised only by R32 from EN, and dropped by FAULT through Q4",
      pg_up == ["R32"] and PIN[("R32", "1")] == "EN"
      and PIN[("Q4", fet_pins("Q4")["G"])] == "FAULT"
      and PIN[("Q4", fet_pins("Q4")["D"])] == "PRE_G")

print()
if FAILED:
    print(f"FAIL  {len(FAILED)} interlock check(s)")
    sys.exit(1)
print("PASS  interlock structure")
