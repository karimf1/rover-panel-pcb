# rover-panel-pcb 

The PCB was missing. It sits on
four standoffs on the panel plate, between the shunt and the signal
connector, and does three jobs:

- **precharge** — it switches the pack through the panel's 22 Ω resistor `R1`
  into the ESC bank, and holds contactor `K1` open until the switched bus
  reaches ~90 % of the pack
- **interlock** — `K1`'s coil is energised through the E-stop loop *and* this
  board, so the board can open `K1` but nothing on it can close `K1` past an
  open E-stop
- **current sense** — an INA228 on the panel's 0.75 mΩ shunt `RS1`, reported
  over I2C

![Board](docs/img/board-3d.png)

It replaces two of the panel's bought parts — `K2`, an automotive precharge
relay, and `A1`, an INA228 breakout on standoffs — and it answers two of the
panel's open questions: *"precharge is sized by hand and is not in any check"*
and *"is the E-stop hard-wired in series with the contactor coil?"*

The one claim the board is built to prove:

> **K1 cannot close unless the E-stop loop is closed AND the host has raised a
> fresh ARM edge AND the switched bus has reached the precharge threshold** —
> and that is hardware, checked against the exported netlist, not a promise
> made by firmware. There is no firmware.

---

## 1. How the interlock works

The logic is four comparators, one AND gate and one D flip-flop. Every node
that feeds the interlock is an open-collector output pulled up **to EN, not to
5 V** — so the instant the board disarms, every one of them falls with it.

| signal | made by | means |
|---|---|---|
| `ESTOP_OK` | U3C: the *far* side of the E-stop loop (`COIL_POS`) above 13.7 V | the mushroom switch is closed |
| `ARM` | U3D: host line above 1.37 V, 100 k pull-down | the host asked; an unplugged harness reads as *no* |
| `CLR#` | U4: `ARM AND ESTOP_OK` | either one dropping clears the latch immediately |
| `EN` | U5 (74LVC1G74) Q, set only on a **rising edge** of `ARM` delayed 10 ms | armed |
| `CHG` | U3A: switched bus / always-on bus **below** the threshold | precharging |
| `FAULT` | U3B: `CHG` has been high longer than the timer (≥ 1.68 s) | the bus is not charging — latches |
| `K1_G` | `EN`, pulled low by `CHG` (Q2) or `FAULT` (Q3), 1 ms RC | close the contactor |
| `PRE_G` | `EN`, pulled low by `FAULT` (Q4) | precharge switch on |

The flip-flop is there for one reason. With a plain AND gate, releasing the
E-stop while the host is still asserting `ARM` would re-energise the drive
motors on its own. With the latch, **an E-stop release does nothing until the
host drops `ARM` and raises it again.** That is what competition rules mean by
a deliberate restart, and it is scenario 5 in the simulation below.

The K1 coil path is:

```
+24 V -> P1.8 -> J1 -> E-stop -> J1 -> P1.3 -> P1.4 -> K1 coil -> P1.6 -> Q1 -> GND
```

`Q1` is on the low side. It can only *interrupt* that loop.

## 2. The design numbers

### Precharge threshold: a window, not a number

The comparator does not measure "90 % of 24 V". It compares two dividers —
the switched bus against the always-on bus — so it holds from a 21 V cutoff
to a 29.4 V full pack. Its threshold still moves, for three reasons, and
`calcs.pre_ratio_window()` takes every corner of all three:

- the hysteresis resistor injects a fixed 5 V into a divider of a *varying*
  pack, so the trip point shifts with pack voltage
- the four ratio resistors. They are 0.1 % parts because with 1 % parts the highest
  corner trips at 94.75 %, which is **above** the 94.50 % the bus can reach. The
  board would fault on a low pack.
- the LM339's 5 mV offset plus its 250 nA bias current through each divider

```
precharge threshold window     88.34 .. 91.74 % of pack
bus can reach through R1       94.50 % at 21 V, with 50 mA of ESC idle draw
```

**The ESC idle draw is the constraint.** The bus charges towards
`V − I_idle × R1`, not towards `V`. At a 21 V pack and 50 mA of idle current,
R1 takes 1.1 V off the target, and a threshold set at the textbook 95 % would
never be reached — the board would fault on every power-up. The 50 mA is
assumed and is the first thing to measure (§6).

### The fault timer has to outlast a slow precharge

```
precharge time, nominal        0.41 s    (6 mF, 25.9 V)
precharge time, worst          0.73 s    (9 mF, 21 V, highest threshold)
fault timer                    1.68 / 2.36 / 2.66 s   (min / nom / max)
```

The minimum assumes the 10 µF X7R timing capacitor has lost 25 % to tolerance
and DC bias, and that the comparator's full bias current is helping to charge
it. That still leaves 2.3× margin over the slowest legitimate precharge. The
maximum is bounded too: into a dead short, `R1` sees 41 W, inside its 50 W
continuous rating, for as long as the timer takes.

### The panel's supply budget

The panel's `params.py` reserves a supply for the board: a 2 A time-lag fuse on
`DIN2-203`, 18 AWG, 0.2 A continuous and a 2.5 A peak. The panel's
`sizing.py` sizes the wiring from those numbers, and this board checks that
its worst case fits inside them. Neither side can quietly outgrow the other.

```
24 V draw                      76 mA continuous (70 mA of it is K1's hold current)
                               2.17 A worst instant: K1 pull-in while precharge still conducts
```

### Everything else

| check | result |
|---|---|
| INA228 full scale at `ADCRANGE = 0` | 218 A, 0.42 mA per count, `SHUNT_CAL` = 2803 |
| current error at 10 A | 0.31 % (shunt 0.25 %, INA228 gain, offset, filter bias) |
| input TVS SM6T36A | stands off 30.8 V > 29.4 V; clamps 49.9 V < 60 V (every FET on the 24 V side) |
| K1 FET gate drive | 4.85 V on a 5 V −2 % rail, ≥ the 4.5 V its RDS(on) is quoted at |
| K1 coil at pack cutoff | 19.8 V ≥ 16 V pickup, after the E-stop loop, the FET and panel wiring |
| precharge FET gate | zener-clamped, ≤ 12.6 V worst case, from 21 V to 29.4 V (fully on, under ±20 V) |
| every LM339 input | inside `VCC − 1.5 V` at a full pack |
| power traces | 1.0 mm vs 0.70 mm IPC-2221 at 2.5 A as if continuous |

### The behaviour, simulated

`test_calcs.py` finishes with a 1 ms-step simulation of the interlock built
from those same thresholds and time constants — nothing retuned for the test:

```
PASS  power-up, ARM low: nothing switches
PASS  ARM with a healthy bus (3 mF): precharge, then K1, no fault  -- K1 closes 0.20 s after ARM, bus at 90.7 %
PASS  ARM with a healthy bus (9 mF): precharge, then K1, no fault  -- K1 closes 0.58 s after ARM, bus at 90.7 %
PASS  ARM into a shorted bus: FAULT latches, precharge stops, K1 never closes  -- fault 2.36 s after ARM
PASS  E-stop opens while K1 is closed: K1 drops within 1 ms
PASS  E-stop released with ARM still high: K1 stays OPEN (needs a new ARM edge)
PASS  ARM cycled after the E-stop reset: precharge and K1 again
PASS  FAULT holds for as long as ARM stays high (a latch, not a retry loop)
PASS  dropping ARM clears FAULT and leaves everything off
```

## 3. What changed from the plan


1. **It had no latch.** The plan's logic was `ARM AND E-STOP AND PRECHARGED`.
   Writing scenario 4 of the simulation showed what that does: release the
   E-stop with `ARM` still high and the motors come back on by themselves.
   The 74LVC1G74 and its 10 ms clock delay are the fix. KiCad 9 ships no
   74LVC1G74 symbol, so it is generated from a pin map in `spec.py`
   (`hw/gen/gen_lib.py`).
2. **The supply fuse is 2 A, not 1 A.** A 1 A fuse passes the board's 76 mA,
   but K1's 2 A pull-in comes through the same fuse.
3. **No 3.3 V rail.** The plan had an LDO for the INA228. Everything runs at
   5 V instead. The INA228's I2C thresholds do not follow its supply, and
   every output to the host is an open-drain FET, so this 5 V board never
   drives a 3.3 V pin. (That INA228 fact is one of the seven items flagged
   `VERIFY`.)
4. **The board is 110 × 46 mm, not ~90 × 55.** The panel set its height:
   25 mm of signal clearance to `K1` above and to the `DIN2` terminals below
   leaves 46 mm. Width was the only direction left to grow.
5. **The buck's pins are not in the 0.3 mm pack-voltage clearance class.** The
   LM5165's own pins are 0.22 mm apart. A 0.3 mm rule for them fails under the
   footprint itself, so the package sets that spacing.


## 4. The layout

![Top copper](docs/img/board-top.svg)

Placement is by hand, in `hw/gen/gen_pcb.py`, because placement *is* the
layout design:

- **P1** (power, coil, E-stop loop) is on the top edge, towards `K1` and `R1`.
  Its edge row is ground plus the E-stop-return/coil+ pair, which never has
  to leave the connector. Every net that travels is on the inner row.
- **P2** (the Kelvin pair) is on the left edge, facing `RS1`. The INA228 is
  turned so its inputs face P2 and its I2C and ground pins face open board.
- **P3** (signal to `J1`) is on the right edge, with the ESD diodes in a
  column in the same order as its pins.
- The coil FET and its clamps are left of P1, the precharge switch and buck
  are right of P1, the comparators are in the middle, and the LEDs are along
  the bottom edge where the hatch is.

The copper between the pads comes from `hw/gen/autoroute.py`: a 0.1 mm grid
A* router, two layers, that runs inside KiCad's own Python using numpy.

- Obstacles are painted at each net's own clearance class. The net being
  routed dilates the map by however much wider it is, so a 1 mm coil trace
  keeps 0.3 mm from everything, and a 0.2 mm signal can still leave a
  0.5 mm-pitch IC.
- Fine-pitch pads get straight escape stubs first, along their own axis.
- If a net cannot get out, it is **promoted** and the whole board re-routes
  from scratch with that net earlier in the queue. That is the cheapest
  rip-up-and-retry there is. The current layout routes on the first attempt
  in about 30 s.
- The ground pour is computed after routing, so a union-find walks every
  island, pad, via and track. Any ground pad the pour does not actually reach
  gets a real track to one it does. An island touching a via is not
  "connected" if that via lands in a fenced-off pocket on the other layer.

None of that is trusted. **kicad-cli DRC with schematic parity is the judge.**

```
802 track segments, 1753 mm of track (181 mm on B.Cu, the ground plane)
205 vias, all tented
0 DRC violations, 0 unconnected pads, 0 footprint errors
```


## 5. <a name="Fabrication (Sponsored by PCBWay)"></a>Fabrication (Sponsored by PCBWay)

![Board](docs/img/fabtpcb.png)

This board was fabricated by PCBWay (https://www.pcbway.com/orderonline.aspx) through their promotional program. Communication was quick: my questions to their representative were answered within one day. Once the order was confirmed I got an email with all the order details, such as tracking number and estimated arrival date. The PCB arrived sealed in a box, packed in foam rubber, so it reached me undamaged. The website is clear and intuitive to use, even for someone placing an order for the first time (like myself). The board itself is excellent. Every dimension matches the design, the exposed copper and pads line up cleanly with no misalignment, and the overall fabrication quality is top-notch. 

