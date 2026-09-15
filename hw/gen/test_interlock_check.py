#!/usr/bin/env python3
"""A test for the test.

A structural check that passes on the real netlist proves nothing unless it
FAILS on a wrong one. Each mutation below is a plausible mistake -- the kind a
schematic edit makes without anyone noticing -- applied to a copy of the
exported netlist. check_interlock.py must reject every one of them.
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NET = os.path.join(HERE, "..", "rover-panel-supervisor.net")
CHECK = os.path.join(HERE, "check_interlock.py")
src = open(NET).read()


def move_node(text, ref, pin, to_net):
    """Detach (ref, pin) from its net and attach it to `to_net`."""
    node = re.search(r'\s*\(node \(ref "%s"\) \(pin "%s"\)[^\n]*' % (re.escape(ref), pin), text)
    assert node, (ref, pin)
    line = node.group(0)
    text = text.replace(line, "", 1)
    m = re.search(r'(\(net \(code "\d+"\) \(name "/?%s"\)[^\n]*\n)' % re.escape(to_net), text)
    assert m, to_net
    return text[:m.end()] + line.lstrip("\n") + "\n" + text[m.end():]


MUTATIONS = [
    # (what the mistake is, how to make it, the check that must catch it)
    ("a 100 ohm part bridging +24V_IN straight to the coil",
     lambda t: move_node(move_node(t, "R30", "1", "+24V_IN"), "R30", "2", "COIL_POS"),
     "no on-board path from +24V_IN to COIL_POS"),
    ("K1_G pull-up taken from +5V instead of EN (E-stop and ARM bypassed)",
     lambda t: move_node(t, "R29", "1", "+5V"),
     "the ONLY thing that can raise K1_G"),
    ("E-stop sense divider moved to the pack side of the loop",
     lambda t: move_node(t, "R18", "1", "+24V_IN"),
     "VE is a divider off COIL_POS"),
    ("flip-flop /CLR tied high (a released E-stop would re-arm by itself)",
     lambda t: move_node(t, "U5", "6", "+5V"),
     "U5 /CLR = U4 output"),
    ("precharge comparator reading the always-on bus twice",
     lambda t: move_node(t, "R14", "1", "+24V_IN"),
     "VA divides +24V_IN and VS divides SW_SENSE"),
    ("FAULT no longer holds K1 off (Q3 gate moved to GND)",
     lambda t: move_node(t, "Q3", "1", "GND"),
     "K1_G is held low by precharge-in-progress"),
]

failed = []
print("== the interlock check rejects broken netlists ==")
for name, mutate, expect in MUTATIONS:
    with tempfile.NamedTemporaryFile("w", suffix=".net", delete=False) as f:
        f.write(mutate(src))
        path = f.name
    r = subprocess.run([sys.executable, CHECK, path], capture_output=True, text=True)
    os.unlink(path)
    fails = [l.strip()[6:] for l in r.stdout.splitlines()
             if l.strip().startswith("FAIL  ") and "check(s)" not in l]
    caught = r.returncode != 0 and any(expect in f for f in fails)
    print(f"  {'PASS' if caught else 'FAIL'}  {name}  -- "
          + (f"caught by: {expect}" if caught else f"NOT caught by '{expect}' (failed: {fails})"))
    if not caught:
        failed.append(name)
if failed:
    print(f"FAIL  {len(failed)} mutation(s) slipped through")
    sys.exit(1)
print("PASS  every mutation caught")
