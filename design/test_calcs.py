#!/usr/bin/env python3
"""Design self-checks.  `make -C hw check` runs these first.

Two halves:

  1. LIMITS -- every derived number in calcs.py against the constraint it
     exists to meet: a datasheet limit, the panel's supply budget, or the
     timing the interlock depends on.
  2. BEHAVIOUR -- a millisecond-step simulation of the interlock built from
     the same thresholds and time constants, driven through the five
     scenarios the board is for.  The netlist version of the same claim, that
     no copper path lets K1 close past the E-stop, is hw/gen/check_interlock.py.

Exit status 0 only if everything passes.
"""
import math
import sys

import calcs as C
import spec as S

FAILED = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{('  -- ' + detail) if detail else ''}")
    if not cond:
        FAILED.append(name)


print("== design self-checks ==")

# ------------------------------------------------------------------ supply
print("\n  supply")
check("TVS stand-off is above a full pack",
      S.D_TVS_VRM >= S.V_PACK_MAX,
      f"SM6T36A {S.D_TVS_VRM} V >= {S.V_PACK_MAX} V")
check("TVS clamp is below every part on the 24 V side",
      S.D_TVS_VCL < min(S.U1_VIN_ABSMAX, S.U2_VCM_MAX, S.Q1_VDS, S.Q6_VDS,
                        S.QS_VDS, S.D2_VR),
      f"{S.D_TVS_VCL} V vs lowest abs max "
      f"{min(S.U1_VIN_ABSMAX, S.U2_VCM_MAX, S.Q1_VDS, S.Q6_VDS, S.QS_VDS, S.D2_VR)} V")
check("buck starts well below pack cutoff",
      8.0 <= C.v_uvlo_on() <= S.V_PACK_MIN - S.D2_VF - 3.0,
      f"UVLO on at {C.v_uvlo_on():.1f} V")
check("buck EN pin stays low-voltage at full pack",
      C.v_en_at_max() < 5.0, f"{C.v_en_at_max():.2f} V")
check("5 V load fits the LM5165's 150 mA with 3x margin",
      C.i5v_worst() * 3 <= S.U1_IOUT, f"{C.i5v_worst()*1e3:.1f} mA worst case")
check("L1 does not saturate at the PFM peak current",
      S.L1_ISAT >= 1.2 * S.U1_ILIM_PK,
      f"Isat {S.L1_ISAT} A vs 1.2 x {S.U1_ILIM_PK} A")
check("continuous draw fits the panel's supply budget (params.PCB I_CONT)",
      C.i24_cont() <= S.I_BUDGET_CONT,
      f"{C.i24_cont()*1e3:.0f} mA of {S.I_BUDGET_CONT*1e3:.0f} mA")
check("worst instant (K1 pull-in + precharge tail) fits the peak budget",
      C.i24_peak() <= S.I_BUDGET_PEAK,
      f"{C.i24_peak():.2f} A of {S.I_BUDGET_PEAK} A")
check("precharge into a flat bus fits the peak budget",
      C.i_precharge_peak() + C.i24_board(S.V_PACK_MAX) <= S.I_BUDGET_PEAK,
      f"{C.i_precharge_peak():.2f} A + board")
check("no Micro-Fit contact carries more than its rating",
      max(C.i24_peak(), C.i_precharge_peak()) / 2 <= S.CONN_I_PIN
      and S.K1_COIL_INRUSH <= S.CONN_I_PIN,
      "24 V on two pins, coil on one")
check("supply fuse does not blow on the coil inrush (peak <= 2.5 x fuse)",
      C.i24_peak() <= 2.5 * S.FUSE_SUPPLY, f"{C.i24_peak():.2f} A vs {S.FUSE_SUPPLY} A T")

# -------------------------------------------------------------- INA228
print("\n  current sense")
check("INA228 full scale covers the largest current the panel can see",
      C.i_fullscale() >= S.I_MAIN_MAX,
      f"{C.i_fullscale():.0f} A full scale at ADCRANGE = 0")
check("SHUNT_CAL fits its 15-bit register",
      0 < C.shunt_cal() < 2 ** 15, f"SHUNT_CAL = {C.shunt_cal():.0f}")
check("Kelvin filter corner is above the INA228's own bandwidth need, below RF",
      1e3 < C.kelvin_corner() < 200e3, f"{C.kelvin_corner()/1e3:.0f} kHz")
check("current error is under 1 % at a 10 A load",
      C.current_error(10.0) < 0.01, f"{C.current_error(10.0)*100:.2f} %")
check("INA228 common mode covers a full pack with margin",
      S.U2_VCM_MAX >= 2 * S.V_PACK_MAX, f"{S.U2_VCM_MAX} V vs {S.V_PACK_MAX} V")
check("INA228 resolution is under 1 mA",
      C.i_resolution() < 1e-3, f"{C.i_resolution()*1e3:.2f} mA per count")

# ----------------------------------------------------------- comparators
print("\n  comparators")
cm = C.cm_inputs()
cm_lim = S.V5 * (1 - S.V5_TOL) - S.U3_CM_HEADROOM
for k, vv in cm.items():
    check(f"LM339 input {k} stays inside the common-mode range",
          vv <= cm_lim, f"{vv:.2f} V <= {cm_lim:.2f} V")

lo, hi = C.pre_ratio_window()
settle = C.v_settle_ratio(S.V_PACK_MIN)
check("precharge threshold (highest corner) is reachable through R1 at cutoff",
      hi <= settle - 0.02,
      f"trips by {hi*100:.2f} %, bus settles at {settle*100:.2f} % -- "
      f"{(settle-hi)*100:.1f} points of margin")
check("precharge threshold (lowest corner) never closes K1 onto >15 % of pack",
      lo >= S.PRE_RATIO_MIN_ALLOWED,
      f"lowest release {lo*100:.2f} %")
check("precharge hysteresis is real at both pack extremes",
      all(C.pre_ratio(v, True) - C.pre_ratio(v, False) > 0.005
          for v in (S.V_PACK_MIN, S.V_PACK_MAX)),
      ", ".join(f"{(C.pre_ratio(v, True)-C.pre_ratio(v, False))*100:.2f} pts @ {v:g} V"
                for v in (S.V_PACK_MIN, S.V_PACK_MAX)))

tmin, tnom, tmax = C.t_trip()
tpre = C.t_precharge_worst()
check("fault timer outlasts the slowest legitimate precharge by 1.5x",
      tmin >= 1.5 * tpre,
      f"timer >= {tmin:.2f} s, precharge <= {tpre:.2f} s "
      f"(9 mF, 21 V, highest threshold)")
check("fault timer is not so long that R1 cooks into a dead short",
      S.V_PACK_MAX ** 2 / (S.R_PRE * (1 - S.R_PRE_TOL)) <= S.R_PRE_P_RATED,
      f"{S.V_PACK_MAX**2/(S.R_PRE*(1-S.R_PRE_TOL)):.0f} W into a {S.R_PRE_P_RATED:.0f} W part "
      f"for {tmax:.1f} s ({C.r1_energy_fault():.0f} J) -- within its continuous rating")
check("fault latch holds TMR well above VREF_T",
      C.v_tmr_latched() >= C.vref_t(1) + 0.5,
      f"{C.v_tmr_latched():.2f} V vs {C.vref_t(0):.2f} V")
check("E-stop sense threshold sits between noise and pack cutoff",
      8.0 <= C.v_estop_threshold() <= 0.8 * S.V_PACK_MIN,
      f"loop reads closed above {C.v_estop_threshold():.1f} V")
check("ARM threshold is LVTTL-compatible (VIL 0.8 V < th < VIH 2.0 V)",
      0.8 < C.v_arm_threshold() < 2.0, f"{C.v_arm_threshold():.2f} V at the host pin")
check("ARM clock delay is long against the AND gate, short against a human",
      1e-3 <= S.R_ARM_DLY * S.C_ARM_DLY <= 50e-3,
      f"{S.R_ARM_DLY*S.C_ARM_DLY*1e3:.0f} ms")
check("precharge comparator is far faster than the K1 gate delay",
      C.t_k1_gate_delay() >= 1e-4, f"K1_G time constant {C.t_k1_gate_delay()*1e3:.1f} ms")

# ---------------------------------------------------------------- switches
print("\n  switches")
check("K1 FET gets the gate voltage its RDS(on) is specified at",
      C.v_k1_gate() >= S.Q1_VGS_SPEC,
      f"{C.v_k1_gate():.2f} V on a 5 V -2 % rail")
check("K1 FET survives the coil inrush pulse",
      C.q1_pulse_energy() < 0.5, f"{C.q1_pulse_energy()*1e3:.0f} mJ in a SOT-223")
check("K1 FET drain is clamped below its rating",
      S.D_TVS_VCL < S.Q1_VDS, f"{S.D_TVS_VCL} V < {S.Q1_VDS} V")
check("K1 coil sees its pickup voltage at pack cutoff",
      C.v_coil_min() >= S.K1_PICKUP_V,
      f"{C.v_coil_min():.1f} V >= {S.K1_PICKUP_V} V pickup")
check("precharge FET is fully enhanced from cutoff to full",
      all(S.Q6_VGS_SPEC <= C.q6_vgs(v) <= S.Q6_VGS_MAX
          for v in (S.V_PACK_MIN, S.V_PACK_MAX)),
      f"VGS {C.q6_vgs(S.V_PACK_MIN):.1f} .. {C.q6_vgs(S.V_PACK_MAX):.1f} V")
check("precharge FET peak loss is SOT-223-sized",
      C.q6_loss_peak() < 1.0, f"{C.q6_loss_peak():.2f} W at {C.i_precharge_peak():.2f} A")

# ------------------------------------------------------------------ copper
print("\n  copper")
w_need = C.ipc2221_width_mm(S.I_BUDGET_PEAK)
check("power traces carry the peak budget as if it were continuous",
      S.W_POWER >= w_need,
      f"{S.W_POWER} mm vs IPC-2221 {w_need:.2f} mm at {S.I_BUDGET_PEAK} A, {S.IPC_DT:.0f} K")
check("power clearance is above IPC-2221 B2 for 31-50 V transients",
      S.CLEARANCE_POWER >= 0.1, f"{S.CLEARANCE_POWER} mm")
check("fab minimums are respected",
      S.W_SIGNAL >= S.FAB_MIN_TRACE and S.CLEARANCE_POWER >= S.FAB_MIN_CLEARANCE)


# ================================================================ behaviour
def simulate(events, t_end, short=False, c_bus=6e-3, v=S.V_PACK_NOM, dt=1e-3):
    """The interlock, one millisecond at a time.

    events: {time_s: {"arm": bool, "estop": bool}} -- estop True = loop closed.
    Returns a list of (t, state dict).  Every threshold and time constant is
    the one calcs.py computed from spec.py; nothing is retuned for the test.
    """
    arm_in, estop = False, False
    q = False
    arm_dly = 0.0
    clk_prev = False
    pre_ok = False
    tmr = 0.0
    k1g = 0.0
    vsw = 0.0
    rise, fall = C.pre_ratio(v, True), C.pre_ratio(v, False)
    vref_t = C.vref_t(0)
    tau_t = (S.R_TMR + S.R_PULLUP) * S.C_TMR
    tau_k = S.R_PULLUP * S.C_K1G
    tau_d = S.R_ARM_DLY * S.C_ARM_DLY
    out = []
    n = int(round(t_end / dt))
    fault = False
    for i in range(n + 1):
        t = i * dt
        for te in sorted(events):
            if abs(te - t) < dt / 2:
                arm_in = events[te].get("arm", arm_in)
                estop = events[te].get("estop", estop)
        coil_pos = v if estop else 0.0
        estop_ok = coil_pos > C.v_estop_threshold()
        arm = arm_in
        clr_n = arm and estop_ok
        arm_dly += ((S.V5 if arm else 0.0) - arm_dly) * dt / tau_d
        clk = arm_dly > S.V5 / 2
        if not clr_n:
            q = False
        elif clk and not clk_prev:
            q = True
        clk_prev = clk
        en = q
        ratio = vsw / v
        pre_ok = ratio > (fall if pre_ok else rise)
        chg = en and not pre_ok
        fault = en and tmr > vref_t
        tmr += ((S.V5 if chg else 0.0) - tmr) * dt / tau_t
        if fault:
            tmr = max(tmr, C.v_tmr_latched())
        k1g_target = S.V5 if (en and not chg and not fault) else 0.0
        k1g += (k1g_target - k1g) * min(1.0, dt / tau_k)
        k1 = k1g > QS_ON and coil_pos >= S.K1_PICKUP_V
        pre_on = en and not fault
        if k1:
            vsw = v
        else:
            i_in = (v - vsw) / S.R_PRE if pre_on else 0.0
            i_load = vsw / 0.05 if short else (S.I_PRE_IDLE if vsw > 1.0 else 0.0)
            vsw = max(0.0, vsw + (i_in - i_load) * dt / c_bus)
        out.append((t, dict(arm=arm, estop=estop, en=en, chg=chg, fault=fault,
                            k1=k1, pre_on=pre_on, vsw=vsw, tmr=tmr)))
    return out


QS_ON = 2.0          # Q1 treated as on above 2 V of gate


def first(trace, key, val=True, after=0.0):
    for t, s in trace:
        if t >= after and s[key] == val:
            return t
    return None


def always(trace, pred, t0, t1):
    return all(pred(s) for t, s in trace if t0 <= t <= t1)


print("\n  behaviour (1 ms simulation of the interlock)")

# 1. power-up with nothing asked for
tr = simulate({0.0: {"arm": False, "estop": True}}, 1.0)
check("power-up, ARM low: nothing switches",
      always(tr, lambda s: not s["k1"] and not s["pre_on"], 0, 1.0))

# 2. healthy arm at both ends of the bus-capacitance range
for cb in (S.C_BUS_MIN, S.C_BUS_MAX):
    tr = simulate({0.0: {"estop": True}, 0.2: {"arm": True}}, 3.0, c_bus=cb)
    tk = first(tr, "k1")
    tf = first(tr, "fault")
    # the bus the instant BEFORE K1 closed -- afterwards it is the pack
    at_close = next((s["vsw"] / S.V_PACK_NOM for t, s in reversed(tr)
                     if tk is not None and t < tk), None)
    check(f"ARM with a healthy bus ({cb*1e3:.0f} mF): precharge, then K1, no fault",
          tk is not None and tf is None and at_close is not None and at_close >= S.PRE_RATIO_MIN_ALLOWED,
          f"K1 closes {tk-0.2:.2f} s after ARM, bus at {at_close*100:.1f} %" if tk else "K1 never closed")

# 3. shorted switched bus
tr = simulate({0.0: {"estop": True}, 0.2: {"arm": True}}, 4.0, short=True)
tf = first(tr, "fault")
check("ARM into a shorted bus: FAULT latches, precharge stops, K1 never closes",
      tf is not None and not any(s["k1"] for _, s in tr)
      and always(tr, lambda s: not s["pre_on"], tf + 0.002, 4.0),
      f"fault {tf-0.2:.2f} s after ARM" if tf else "no fault")

# 4. E-stop while running, then reset with ARM still asserted
tr = simulate({0.0: {"estop": True}, 0.2: {"arm": True},
               2.0: {"estop": False}, 3.0: {"estop": True}}, 5.0)
check("E-stop opens while K1 is closed: K1 drops within 1 ms",
      first(tr, "k1", False, after=2.0) is not None
      and first(tr, "k1", False, after=2.0) <= 2.001)
check("E-stop released with ARM still high: K1 stays OPEN (needs a new ARM edge)",
      always(tr, lambda s: not s["k1"] and not s["pre_on"], 2.002, 5.0))

# 5. ... and a deliberate re-arm brings it back
tr = simulate({0.0: {"estop": True}, 0.2: {"arm": True}, 2.0: {"estop": False},
               3.0: {"estop": True}, 3.5: {"arm": False}, 3.7: {"arm": True}}, 6.0)
check("ARM cycled after the E-stop reset: precharge and K1 again",
      first(tr, "k1", True, after=3.7) is not None)

# 6. a fault is a latch: it holds while ARM is held, and only dropping ARM clears it
tr = simulate({0.0: {"estop": True}, 0.2: {"arm": True}, 5.0: {"arm": False}},
              8.0, short=True)
tf = first(tr, "fault")
check("FAULT holds for as long as ARM stays high (a latch, not a retry loop)",
      tf is not None and always(tr, lambda s: s["fault"] and not s["pre_on"], tf, 4.999),
      f"latched from {tf-0.2:.2f} s to ARM release" if tf else "no fault")
check("dropping ARM clears FAULT and leaves everything off",
      always(tr, lambda s: not s["fault"] and not s["k1"] and not s["pre_on"], 5.001, 8.0))

# ==================================================================== report
print("\n== numbers ==")
print(f"  precharge threshold window     {lo*100:.2f} .. {hi*100:.2f} % of pack")
print(f"  precharge time, nominal        {C.t_precharge_nominal():.2f} s")
print(f"  precharge time, worst          {tpre:.2f} s")
print(f"  fault timer                    {tmin:.2f} / {tnom:.2f} / {tmax:.2f} s  (min/nom/max)")
print(f"  fault reset after ARM drops    {C.t_fault_reset():.2f} s")
print(f"  E-stop loop reads closed above {C.v_estop_threshold():.1f} V")
print(f"  INA228 SHUNT_CAL               {C.shunt_cal():.0f}  (CURRENT_LSB {C.current_lsb()*1e6:.1f} uA)")
print(f"  24 V draw                      {C.i24_cont()*1e3:.0f} mA continuous, {C.i24_peak():.2f} A peak")

print("\n== VERIFY before ordering (quoted from memory, not from a PDF on disk) ==")
for v_ in S.VERIFY:
    print(f"  - {v_}")

if FAILED:
    print(f"\nFAIL  {len(FAILED)} check(s): " + "; ".join(FAILED))
    sys.exit(1)
print("\nPASS  design self-checks")
