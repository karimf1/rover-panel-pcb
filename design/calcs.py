"""Derived quantities.  Every function returns a number; the reasoning is in
its docstring; test_calcs.py turns the numbers into PASS/FAIL.

The two that decide whether the board works at all are pre_ratio() and
t_trip(): the precharge comparator has to trip below the voltage the bus can
actually reach through R1, and the fault timer has to outlast the slowest
legitimate precharge.  Both are worst-cased over resistor tolerance, the
comparator's offset and bias current, the bus-capacitance range nobody has
measured, and the pack voltage from cutoff to full.
"""
import itertools
import math

import spec as S


def par(a, b):
    return a * b / (a + b)


# ------------------------------------------------------------------- supply
def v_uvlo_on():
    """Pack voltage at which the buck starts: EN divider against EN_TH."""
    return S.U1_EN_TH * (S.R_EN_TOP + S.R_EN_BOT) / S.R_EN_BOT


def v_en_at_max():
    return (S.V_PACK_MAX - S.D2_VF) * S.R_EN_BOT / (S.R_EN_TOP + S.R_EN_BOT)


def i5v_worst():
    """Worst-case 5 V load, A."""
    led = S.N_LED_WORST * (S.V5 - S.LED_VF) / S.R_LED
    pullups_to_5v = 2 * S.V5 / S.R_PULLUP            # ARM, ESTOP_OK nodes low
    pullups_to_en = 4 * S.V5 / S.R_PULLUP            # CHG, FAULT, K1_G, PRE_G
    vref = S.V5 / (S.R_VREF_TOP + S.R_VREF_BOT) + S.V5 / (S.R_VREFT_TOP + S.R_VREFT_BOT)
    ics = S.U3_ICC + S.U2_IQ + 2 * 0.1e-3             # LM339, INA228, 2 x LVC
    return led + pullups_to_5v + pullups_to_en + vref + ics


def i24_board(v=None):
    """Board current from the 24 V supply, excluding the K1 coil, A."""
    v = S.V_PACK_MIN if v is None else v
    buck = S.V5 * i5v_worst() / S.U1_EFF / (v - S.D2_VF)
    dividers = v / (S.R_VA_TOP + S.R_VA_BOT) + v / (S.R_VE_TOP + S.R_VE_BOT) \
        + v / (S.R_EN_TOP + S.R_EN_BOT)
    gate = (v - S.DZ_V) / S.R_PG_DRV if v > S.DZ_V else 0.0
    return buck + dividers + gate


def i24_cont():
    """Continuous: board + coil hold (precharge current is zero once K1 closes)."""
    return i24_board() + S.K1_COIL_HOLD


def i24_peak():
    """The worst instant: K1 pulling in while precharge still conducts.

    Precharge and coil inrush overlap for exactly one reason -- the precharge
    FET stays on after K1 closes -- and at that instant the bus is already at
    the comparator threshold, so R1 carries at most (1 - ratio) of the pack.
    """
    lo, _ = pre_ratio_window()
    i_pre = S.V_PACK_MAX * (1 - lo) / (S.R_PRE * (1 - S.R_PRE_TOL))
    return i24_board(S.V_PACK_MAX) + S.K1_COIL_INRUSH + i_pre


def i_precharge_peak():
    """Precharge current into a fully discharged bus: pack / R1."""
    return S.V_PACK_MAX / (S.R_PRE * (1 - S.R_PRE_TOL))


# ---------------------------------------------------------------- INA228
def current_lsb():
    return S.I_MAIN_MAX / 2 ** 19


def shunt_cal():
    return S.U2_CAL_K * current_lsb() * S.SHUNT_R


def i_fullscale():
    return S.U2_SHUNT_FS / S.SHUNT_R


def i_resolution():
    return S.U2_SHUNT_LSB / S.SHUNT_R


def kelvin_corner():
    """Differential corner of the two 10 ohm resistors and the 100 nF cap."""
    return 1 / (2 * math.pi * 2 * S.R_KELVIN * S.C_KELVIN)


def current_error(i):
    """Worst-case relative current error at `i` amps.

    Shunt tolerance + INA228 gain error + offset referred to current + the
    bias current flowing in ONE 10 ohm filter resistor (the worst case is all
    of it appearing as differential voltage).
    """
    v = i * S.SHUNT_R
    return S.SHUNT_TOL + S.U2_GAIN_ERR + (S.U2_OFFSET + S.U2_IB * S.R_KELVIN) / v


# ------------------------------------------------------ precharge comparator
def _pre_ratio(v, r_va_t, r_va_b, r_vs_t, r_vs_b, vchg, vos, rising):
    """Switched/always-on bus ratio at which the comparator changes state.

    VA = the always-on bus through R12/R13, pulled by R16 towards the CHG node
         (5 V while precharging, ~0 once PRE_OK).  That feedback IS the
         hysteresis, and because it injects a fixed 5 V into a divider of a
         varying pack voltage, the threshold moves with pack voltage.
    VS = the switched bus through R14/R15.
    The output flips when VS crosses VA + offset.
    """
    th = par(r_va_t, r_va_b)
    va = (v * r_va_b / (r_va_t + r_va_b) * S.R_PRE_HYST + vchg * th) / (S.R_PRE_HYST + th)
    vs_needed = va + (vos if rising else -vos)
    return vs_needed * (r_vs_t + r_vs_b) / r_vs_b / v


def pre_ratio(v, rising=True, corner=None):
    """`corner` flips each ratio resistor to +/- its tolerance and the input
    error to +/- its maximum.  The input error is the LM339's offset plus its
    bias current flowing out of the input through that divider's Thevenin
    resistance -- a few mV on a ~2 V signal, but it is in the window."""
    tol = S.R_TOL_RATIO
    if corner is None:
        corner = (0, 0, 0, 0, 0)
    fa_t, fa_b, fs_t, fs_b, fos = corner
    vchg = S.V5 if rising else 0.2
    verr = S.U3_VOS + S.U3_IB_MAX * par(S.R_VS_TOP, S.R_VS_BOT)
    return _pre_ratio(v, S.R_VA_TOP * (1 + fa_t * tol), S.R_VA_BOT * (1 + fa_b * tol),
                      S.R_VS_TOP * (1 + fs_t * tol), S.R_VS_BOT * (1 + fs_b * tol),
                      vchg, fos * verr, rising)


def pre_ratio_window():
    """(lowest falling threshold, highest rising threshold) over every corner
    of resistor tolerance and offset, at both ends of the pack range."""
    lo, hi = 9.0, 0.0
    for v in (S.V_PACK_MIN, S.V_PACK_MAX):
        for c in itertools.product((-1, 1), repeat=5):
            hi = max(hi, pre_ratio(v, True, c))
            lo = min(lo, pre_ratio(v, False, c))
    return lo, hi


def v_settle_ratio(v):
    """How close to the pack the switched bus gets through R1 with the ESCs idling."""
    return (v - S.I_PRE_IDLE * S.R_PRE * (1 + S.R_PRE_TOL)) / v


def t_precharge(v, c_bus, ratio):
    """Time for the switched bus to reach `ratio` of pack through R1, s.

    The bus charges towards v - I_idle * R1, not towards v, which is why the
    ESC idle draw matters: at 21 V and 50 mA it takes 1.1 V off the target,
    and the comparator threshold has to sit below what is left.
    """
    r = S.R_PRE * (1 + S.R_PRE_TOL)
    vfin = v - S.I_PRE_IDLE * r
    x = ratio * v / vfin
    if x >= 1:
        return math.inf
    return -r * c_bus * math.log(1 - x)


def t_precharge_worst():
    _, hi = pre_ratio_window()
    return max(t_precharge(v, S.C_BUS_MAX, hi) for v in (S.V_PACK_MIN, S.V_PACK_MAX))


def t_precharge_nominal():
    return t_precharge(S.V_PACK_NOM, (S.C_BUS_MIN + S.C_BUS_MAX) / 2, pre_ratio(S.V_PACK_NOM))


# ----------------------------------------------------------------- fault timer
def _t_trip(r, c, vref, vchg, ib):
    """Time for TMR to reach VREF_T from 0 V, charged from CHG through
    R_PULLUP + R_TMR, with the comparator's bias current flowing out of its +
    input INTO the node (it is a PNP input stage) -- which shortens the trip."""
    rt = r + S.R_PULLUP
    vinf = vchg + ib * rt
    if vref >= vinf:
        return math.inf
    return -rt * c * math.log(1 - vref / vinf)


def vref_t(corner=0):
    return S.V5 * S.R_VREFT_BOT * (1 + corner * S.R_TOL) / \
        (S.R_VREFT_TOP * (1 - corner * S.R_TOL) + S.R_VREFT_BOT * (1 + corner * S.R_TOL))


def t_trip():
    """(min, nominal, max) fault-timer trip time, s.

    VREF_T and CHG both come off the same 5 V rail, so rail tolerance cancels;
    what does not cancel is the divider ratio, R, C and the bias current."""
    nom = _t_trip(S.R_TMR, S.C_TMR, vref_t(0), S.V5, 0.0)
    lo = _t_trip(S.R_TMR * (1 - S.R_TOL), S.C_TMR * (1 - S.C_TMR_TOL_LO),
                 vref_t(-1), S.V5, S.U3_IB_MAX)
    hi = _t_trip(S.R_TMR * (1 + S.R_TOL), S.C_TMR * (1 + S.C_TMR_TOL_HI),
                 vref_t(+1), S.V5, 0.0)
    return lo, nom, hi


def v_tmr_latched():
    """TMR while FAULT holds it: 5 V through R_PULLUP and the latch diode,
    against R_TMR discharging into a CHG node that may be low."""
    i = (S.V5 - S.V_DIODE_LATCH) / (S.R_PULLUP + S.R_TMR)
    return S.V5 - S.V_DIODE_LATCH - i * S.R_PULLUP


def t_fault_reset():
    """After ARM drops: TMR decays from the latched voltage below VREF_T."""
    return (S.R_TMR + S.R_PULLUP) * S.C_TMR * math.log(v_tmr_latched() / vref_t(0))


def r1_energy_fault():
    """Energy into R1 if the bus is a dead short, until the timer trips, J."""
    _, _, hi = t_trip()
    return S.V_PACK_MAX ** 2 / (S.R_PRE * (1 - S.R_PRE_TOL)) * hi


# --------------------------------------------------------------- the others
def v_estop_threshold():
    vref = S.V5 * S.R_VREF_BOT / (S.R_VREF_TOP + S.R_VREF_BOT)
    return vref * (S.R_VE_TOP + S.R_VE_BOT) / S.R_VE_BOT


def v_arm_threshold():
    vref = S.V5 * S.R_VREF_BOT / (S.R_VREF_TOP + S.R_VREF_BOT)
    return vref * (S.R_ARM_SER + S.R_ARM_PD) / S.R_ARM_PD


def cm_inputs():
    """Highest voltage at each comparator input in normal operation, V."""
    vmax = S.V_PACK_MAX
    return {
        "VA": vmax * S.R_VA_BOT / (S.R_VA_TOP + S.R_VA_BOT) + 0.05,
        "VS": vmax * S.R_VS_BOT / (S.R_VS_TOP + S.R_VS_BOT),
        "VE": vmax * S.R_VE_BOT / (S.R_VE_TOP + S.R_VE_BOT),
        "VARM(3.3 V host)": 3.3 * S.R_ARM_PD / (S.R_ARM_SER + S.R_ARM_PD),
        "VREF": S.V5 * S.R_VREF_BOT / (S.R_VREF_TOP + S.R_VREF_BOT),
        "VREF_T": vref_t(0),
    }


def v_k1_gate():
    """K1_G high: EN through R_PULLUP against the 1 M pull-down, worst rail."""
    v = S.V5 * (1 - S.V5_TOL)
    return v * S.R_K1G_PD / (S.R_PULLUP + S.R_K1G_PD)


def t_k1_gate_delay():
    """K1_G rises no faster than R_PULLUP * C_K1G: CHG always wins the race."""
    return S.R_PULLUP * S.C_K1G


def v_coil_min():
    """Coil voltage at pull-in, worst case: pack cutoff less the E-stop loop,
    the NDT3055L and the panel wiring (sizing.py branch B9 drop, taken as
    the 3 % budget to be safe)."""
    loop = S.K1_COIL_INRUSH * S.R_18AWG_70C * S.L_ESTOP_LOOP
    fet = S.K1_COIL_INRUSH * S.Q1_RDS_4V5
    panel = 0.03 * S.V_PACK_NOM
    return S.V_PACK_MIN - loop - fet - panel


def q1_pulse_energy():
    return S.K1_COIL_INRUSH ** 2 * S.Q1_RDS_4V5 * S.K1_COIL_INRUSH_T


def q6_vgs(v):
    """Precharge FET gate: 47 k gate-source, 12 V zener, 10 k to the 2N7002."""
    free = v * S.R_PG_GS / (S.R_PG_GS + S.R_PG_DRV)
    return min(free, S.DZ_V * (1 + S.DZ_TOL))


def q6_loss_peak():
    return i_precharge_peak() ** 2 * S.Q6_RDS_10V


def ipc2221_width_mm(i, dt=S.IPC_DT, oz=S.CU_OZ):
    """IPC-2221 external-layer width for current i at temperature rise dt."""
    area_mil2 = (i / (0.048 * dt ** 0.44)) ** (1 / 0.725)
    return area_mil2 / (1.378 * oz) * 0.0254
