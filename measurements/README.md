# Measurements — template, nothing measured yet

Every number in the project README is a calculation. This is where the
measurements that replace them go, one table per test, with the scope
captures beside them.

## Bench setup

| item | value |
|---|---|
| supply | bench PSU at 21.0 V, 25.9 V and 29.4 V (7S cutoff, nominal, full) |
| switched bus | capacitor bank standing in for the ESCs: 3 mF and 9 mF |
| ESC idle draw | electronic load in CC mode on the bus: 0, 50 and 100 mA |
| K1 | the real contactor, or a 24 V relay coil of similar inrush |
| R1 | the panel's 22 R 50 W resistor |
| probes | CH1 bus, CH2 `CHG` (TP4), CH3 `TMR` (TP5), CH4 `K1_G` (TP7) |

## 1. Precharge threshold

The prediction is 88.3–91.7 % of pack, from `calcs.pre_ratio_window()`.

| pack V | idle mA | bus V when `CHG` falls | ratio | predicted |
|---|---|---|---|---|
| 21.0 | 50 | | | 88.3 – 91.7 % |
| 25.9 | 50 | | | |
| 29.4 | 50 | | | |
| 21.0 | 100 | | | must still reach the threshold |

## 2. Precharge time and fault timer

| bus C | pack V | ARM -> K1_G high (s) | predicted | shorted bus: ARM -> FAULT (s) | predicted |
|---|---|---|---|---|---|
| 3 mF | 25.9 | | 0.20 (simulated) | | 1.68 – 2.66 |
| 9 mF | 21.0 | | 0.73 worst | | |

## 3. Interlock scenarios (pass / fail)

| # | scenario | expected | result |
|---|---|---|---|
| 1 | power up with ARM low | nothing switches | |
| 2 | ARM, healthy bus | precharge, then K1 | |
| 3 | ARM into a shorted bus | FAULT latches, K1 never closes | |
| 4 | open E-stop with K1 closed | K1 drops | |
| 5 | release E-stop, ARM still high | K1 stays open | |
| 6 | cycle ARM after 5 | precharge and K1 again | |
| 7 | drop ARM during FAULT | FAULT clears after ~1.7 s | |

## 4. INA228 against a reference meter

| load A | reference A | INA228 A | error % | predicted |
|---|---|---|---|---|
| 1 | | | | |
| 10 | | | | < 0.31 % |
| 50 | | | | |
