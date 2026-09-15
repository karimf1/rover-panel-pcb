"""rover-panel-supervisor: every number the board depends on, in one place.

Three kinds of number live here, and each is marked:

  PANEL   read from panel_interface.json, which rover-power-panel/scripts/
          params.py generates.  The board does not get to choose these.
  DS      read off a datasheet; the document is named at the part.
  VERIFY  a datasheet value quoted from memory rather than from a PDF on disk,
          or a behaviour of a pin-strap that has to be confirmed before an
          order.  VERIFY lists every one of them and test_calcs.py prints the
          list on every run, so none of them can be forgotten.
  ASSUMED a property of the rover that nobody has measured yet -- the same
          status as the load table in the panel README.

calcs.py derives everything else; test_calcs.py asserts the limits.
"""
import json
import os

PROJECT = "rover-panel-supervisor"
REV = "A"

HERE = os.path.dirname(os.path.abspath(__file__))
IFACE = json.load(open(os.path.join(HERE, "panel_interface.json")))
BUDGET = IFACE["supply_budget"]

VERIFY = []


def verify(what):
    VERIFY.append(what)


# ============================================================ PANEL (given)
V_PACK_MIN = 21.0                   # PANEL README: 7S cutoff
V_PACK_NOM = 25.9
V_PACK_MAX = BUDGET["v_pack_max"]   # 29.4 V, 7S full
R_PRE = BUDGET["r_precharge_ohm"]   # panel R1, 22 ohm 50 W
R_PRE_TOL = 0.05
R_PRE_P_RATED = 50.0
I_BUDGET_CONT = BUDGET["i_cont_A"]
I_BUDGET_PEAK = BUDGET["i_peak_A"]
I_PRE_IDLE = BUDGET["i_precharge_idle_A"]   # ASSUMED: ESC bank idle draw
FUSE_SUPPLY = BUDGET["fuse_A"]

SHUNT_R = 0.75e-3                   # panel RS1, 100 A / 75 mV
SHUNT_TOL = 0.0025                  # ASSUMED: 0.25 % manganin shunt class
I_MAIN_MAX = 150.0                  # A, largest current the INA228 must report
                                    # (80 A fuse, 100 A peak, headroom)

# ================================================================ ASSUMED
# The switched bus capacitance is the ESC bank's input capacitors.  Nobody has
# counted them (panel README section 11), so precharge is designed over a
# range and every check is run at both ends of it.
C_BUS_MIN = 3.0e-3
C_BUS_MAX = 9.0e-3

# K1: the panel calls it "sealed DC contactor + economiser", 100 A, 24 V coil,
# with no part number yet.  These are the coil numbers of that CLASS of part
# and are replaced with the real datasheet when K1 is bought.
K1_COIL_INRUSH = 2.0                # A, economiser pull-in, ~150 ms
K1_COIL_INRUSH_T = 0.15             # s
K1_COIL_HOLD = 0.07                 # A
K1_PICKUP_V = 16.0                  # V, must-operate at 25 C
K1_INTERNAL_SUPPRESSION = True      # economised coils usually carry their own;
verify("K1 part number: coil inrush/hold/pickup and whether it has internal "
       "coil suppression (if not, add a TVS-limited freewheel path)")

# E-stop loop: out through J1, round the mushroom switch, back.  Same 1.5 m
# the panel's sizing.py declares for segment S26.
L_ESTOP_LOOP = 2 * 1.50             # m of 18 AWG, out and back
R_18AWG_70C = 0.02095 * (1 + 0.00393 * 50)   # ohm/m at 70 C

# ================================================================ PARTS (DS)
# --- U1: TI LM5165X, 5 V fixed synchronous buck, 150 mA, DRC (VSON-10)
U1_VIN_MAX = 65.0                   # DS: recommended max
U1_VIN_ABSMAX = 70.0                # VERIFY
U1_IOUT = 0.150
U1_EN_TH = 1.20                     # VERIFY: EN rising threshold
U1_EFF = 0.80                       # conservative at 20 mA out of 24 V
verify("LM5165X: EN rising threshold 1.2 V, RT tied to GND selects PFM mode, "
       "ILIM tied to GND selects the low peak current limit (R3/R4 are 0R "
       "links so either strap can be changed after checking)")
verify("LM5165X: VIN absolute maximum 70 V")

# --- L1: 220 uH, Coilcraft LPS5030 footprint
L1 = 220e-6
L1_ISAT = 0.34                      # VERIFY
L1_DCR = 3.0                        # VERIFY
U1_ILIM_PK = 0.24                   # VERIFY: PFM peak current, ILIM = GND
verify("L1 (LPS5030-224): saturation current >= LM5165 PFM peak current")

# --- U2: TI INA228, VSSOP-10
U2_VCM_MAX = 85.0                   # DS: common-mode, IN+ / IN- / VBUS
U2_VS_MIN, U2_VS_MAX = 2.7, 5.5     # DS
U2_SHUNT_FS = 163.84e-3             # DS: ADCRANGE = 0
U2_SHUNT_LSB = 312.5e-9             # DS: ADCRANGE = 0
U2_VBUS_LSB = 195.3125e-6           # DS
U2_CAL_K = 13062.5e6                # DS: SHUNT_CAL = K * CURRENT_LSB * R
U2_GAIN_ERR = 0.0005                # DS: +/-0.05 %
U2_OFFSET = 1.0e-6                  # DS: +/-1 uV shunt offset, max
U2_IB = 2.5e-9                      # VERIFY: IN+/IN- bias current
U2_VIH = 1.2                        # VERIFY: I2C VIH independent of VS
U2_IQ = 0.35e-3                     # DS: max
verify("INA228: I2C VIH/VIL independent of VS (lets a 3.3 V host talk to it "
       "at VS = 5 V)")
R_KELVIN = 10.0                     # ohm, DS recommends <= 10 ohm
C_KELVIN = 100e-9

# --- U3: TI LM339, quad open-collector comparator, SOIC-14
U3_VCC_MIN = 2.0
U3_VOS = 5.0e-3                     # DS: max at 25 C
U3_IB_MAX = 250e-9                  # DS: max, flows OUT of the PNP inputs
U3_CM_HEADROOM = 1.5                # DS: inputs valid up to VCC - 1.5 V
U3_ICC = 2.0e-3                     # DS: max, all outputs low
U3_ISINK_OK = 6.0e-3                # DS: VOL <= 0.4 V at 4 mA; 6 mA typ min

# --- U4 74LVC1G08 AND, U5 SN74LVC1G74 D flip-flop with /CLR and /PRE
U5_PINOUT = {"CLK": 1, "D": 2, "~Q": 3, "GND": 4, "Q": 5, "~CLR": 6,
             "~PRE": 7, "VCC": 8}   # VERIFY: DCT package pin map
verify("SN74LVC1G74 DCT (SSOP-8) pin map in lib/rover-panel-supervisor.kicad_sym")

# --- Q1: onsemi NDT3055L, N-FET 60 V 4 A, SOT-223 (K1 coil)
Q1_VDS = 60.0
Q1_RDS_4V5 = 0.120                  # VERIFY: RDS(on) at VGS = 4.5 V
Q1_VGS_SPEC = 4.5
# --- Q6: onsemi NDT2955, P-FET -60 V -2.5 A, SOT-223 (precharge)
Q6_VDS = 60.0
Q6_RDS_10V = 0.30                   # VERIFY
Q6_VGS_MAX = 20.0
Q6_VGS_SPEC = 10.0
verify("NDT3055L / NDT2955 RDS(on) at the gate drive used, and SOT-223 "
       "pin 1 = G, 2 = D, 3 = S, tab = D")
# --- 2N7002 signal FETs
QS_VDS = 60.0
QS_VTH_MAX = 2.5

# --- TVS: ST SM6T36A, 600 W, SMB, unidirectional
D_TVS_VRM = 30.8                    # DS: stand-off
D_TVS_VCL = 49.9                    # DS: clamp at the rated pulse current
# --- reverse-polarity diode: B160, 60 V 1 A Schottky, SMA
D2_VR = 60.0
D2_VF = 0.70
# --- 12 V zener on the precharge gate: BZX384-C12
DZ_V = 12.0
DZ_TOL = 0.05

# --- connectors: Molex Micro-Fit 3.0, 43045 vertical headers
CONN_I_PIN = 5.0                    # A per contact, 18 AWG crimp, derated
CONN_MATED_H = 25.0                 # VERIFY: header + mated plug height

# ================================================================ CHOSEN VALUES
V5 = 5.0
V5_TOL = 0.02
R_TOL = 0.01
R_TOL_RATIO = 0.001                 # 0.1 % on the four precharge ratio resistors

# buck UVLO divider (EN)
R_EN_TOP, R_EN_BOT = 1.0e6, 110e3

# VREF = 5 V * R9 / (R8 + R9): ESTOP and ARM comparators
R_VREF_TOP, R_VREF_BOT = 30.1e3, 10.0e3
# VREF_T = 5 V / 2: fault timer
R_VREFT_TOP, R_VREFT_BOT = 10.0e3, 10.0e3

# precharge ratio comparator: VA from the always-on bus, VS from the switched
R_VA_TOP, R_VA_BOT = 100e3, 9.76e3
R_VS_TOP, R_VS_BOT = 100e3, 11.0e3
R_PRE_HYST = 1.0e6                  # CHG -> VA
PRE_RATIO_MIN_ALLOWED = 0.85        # below this K1 closes onto >15 % of pack

# fault timer
R_PULLUP = 10.0e3                   # every open-collector node
R_TMR = 330e3
C_TMR = 10e-6
C_TMR_TOL_LO, C_TMR_TOL_HI = 0.25, 0.10   # X7R 25 V 1206: tolerance + DC bias
V_DIODE_LATCH = 0.7                 # 1N4148W

# E-stop sense
R_VE_TOP, R_VE_BOT = 100e3, 10.0e3
R_VE_HYST = 1.0e6
# ARM receiver
R_ARM_SER, R_ARM_PD = 10.0e3, 100e3
R_ARM_HYST = 1.0e6
C_ARM = 100e-9
R_ARM_DLY, C_ARM_DLY = 100e3, 100e-9      # CLK delay behind /CLR

# K1 gate
R_K1G_PD = 1.0e6
C_K1G = 100e-9
# precharge gate
R_PG_GS = 47e3
R_PG_DRV = 10e3

# LEDs
R_LED = 1.5e3
LED_VF = 2.0
N_LED_WORST = 4                     # PWR + ESTOP + FAULT + (PRE or K1)

# trace widths (mm) and copper
CU_OZ = 1.0
W_POWER = 1.0
W_SIGNAL = 0.20
CLEARANCE_POWER = 0.30
IPC_DT = 20.0                       # K rise allowed for the power class

# fab: JLCPCB 2-layer standard capability
FAB_MIN_TRACE = 0.127
FAB_MIN_CLEARANCE = 0.127
FAB_MIN_DRILL = 0.3
FAB_MIN_VIA = 0.6
FAB_MIN_EDGE_CLEARANCE = 0.3
