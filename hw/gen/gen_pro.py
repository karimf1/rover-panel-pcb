#!/usr/bin/env python3
"""Write rover-panel-supervisor.kicad_pro: project settings and the net
classes DRC is checked against.

The net classes are the design, not decoration:

  Power    +24V_IN, the E-stop loop / coil wires and the precharge output.
           1.0 mm, from design/calcs.py's IPC-2221 check at the panel's 2.5 A
           peak budget; 0.3 mm clearance because these nets see the TVS clamp
           (49.9 V) during a transient, not just 29.4 V.
  Pack     every other net that sits at pack voltage but carries microamps
           (divider tops, the buck input, the precharge FET gate): signal
           width, power clearance.
  Kelvin   the two shunt sense nets, routed as a pair.
  Default  5 V logic.

Fab minimums are JLCPCB's published 2-layer capability (design/spec.py).
Run AFTER gen_pcb.py: pcbnew's SaveBoard rewrites the project file with
defaults and silently drops the net classes (can-iso-breakout found that).
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..", "design")))
import spec as S  # noqa: E402

NAME = "rover-panel-supervisor"

CLASSES = {
    "Power": ["+24V_IN", "COIL_POS", "COIL_NEG", "PRE_OUT"],
    # VIN_BUCK and BUCK_SW are NOT here, though they sit at pack voltage: they
    # land on the LM5165's 0.5 mm-pitch pins, whose own copper is 0.22 mm apart.
    # A 0.3 mm rule for them would fail under the footprint itself, so the
    # package sets that spacing -- the same call can-iso-breakout made for U2.
    "Pack": ["SW_SENSE", "Q6_G", "PFET_DRV"],
    "Kelvin": ["KELVIN_P", "KELVIN_N", "INA_INP", "INA_INN"],
}


def netclass(name, clearance, track, priority, color=None, diff_w=0.2, diff_g=0.25):
    return {
        "name": name, "clearance": clearance, "track_width": track,
        "via_diameter": 0.6, "via_drill": 0.3, "microvia_diameter": 0.3,
        "microvia_drill": 0.1, "diff_pair_gap": diff_g, "diff_pair_width": diff_w,
        "diff_pair_via_gap": diff_g, "line_style": 0,
        "pcb_color": color or "rgba(0, 0, 0, 0.000)",
        "schematic_color": "rgba(0, 0, 0, 0.000)",
        "wire_width": 6, "bus_width": 12, "priority": priority,
    }


def patterns():
    out = []
    for cls, nets in CLASSES.items():
        for n in nets:
            out += [{"netclass": cls, "pattern": n}, {"netclass": cls, "pattern": "/" + n}]
    return out


PRO = {
    "board": {"3dviewports": [], "design_settings": {
        "defaults": {
            "board_outline_line_width": 0.1, "copper_line_width": 0.2,
            "copper_text_size_h": 1.0, "copper_text_size_v": 1.0,
            "copper_text_thickness": 0.15, "silk_line_width": 0.12,
            "silk_text_size_h": 1.0, "silk_text_size_v": 1.0,
            "silk_text_thickness": 0.15,
        },
        "diff_pair_dimensions": [], "drc_exclusions": [],
        "rules": {
            "max_error": 0.005,
            "min_clearance": S.FAB_MIN_CLEARANCE,
            "min_copper_edge_clearance": S.FAB_MIN_EDGE_CLEARANCE,
            "min_hole_clearance": 0.25, "min_hole_to_hole": 0.5,
            "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1,
            "min_resolved_spokes": 2, "min_silk_clearance": 0.0,
            "min_text_height": 0.8, "min_text_thickness": 0.08,
            "min_through_hole_diameter": S.FAB_MIN_DRILL,
            "min_track_width": S.FAB_MIN_TRACE,
            "min_via_annular_width": 0.13, "min_via_diameter": S.FAB_MIN_VIA,
            "solder_mask_to_copper_clearance": 0.0,
            "use_height_for_length_calcs": True,
        },
        "track_widths": [0.0, S.W_SIGNAL, 0.4, 0.6, S.W_POWER],
        "via_dimensions": [{"diameter": 0.0, "drill": 0.0},
                           {"diameter": 0.6, "drill": 0.3}],
        "zones_allow_external_fillets": False,
    }, "layer_presets": [], "viewports": []},
    "boards": [],
    "cvpcb": {"equivalence_files": []},
    "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
    "meta": {"filename": f"{NAME}.kicad_pro", "version": 3},
    "net_settings": {
        "classes": [
            netclass("Default", 0.2, S.W_SIGNAL, 2147483647),
            netclass("Power", S.CLEARANCE_POWER, S.W_POWER, 1, "rgba(220, 60, 40, 0.700)"),
            netclass("Pack", S.CLEARANCE_POWER, S.W_SIGNAL, 2, "rgba(230, 150, 40, 0.600)"),
            netclass("Kelvin", 0.2, 0.3, 3, "rgba(60, 140, 230, 0.700)", 0.3, 0.25),
        ],
        "meta": {"version": 4},
        "net_colors": None, "netclass_assignments": None,
        "netclass_patterns": patterns(),
    },
    "pcbnew": {"last_paths": {"gencad": "", "idf": "", "netlist": "", "plot": "",
                              "pos_files": "", "specctra_dsn": "", "step": "",
                              "svg": "", "vrml": ""},
               "page_layout_descr_file": ""},
    "schematic": {
        "annotate_start_num": 0,
        "drawing": {"dashed_lines_dash_length_ratio": 12.0,
                    "dashed_lines_gap_length_ratio": 3.0,
                    "default_line_thickness": 6.0, "default_text_size": 50.0,
                    "field_names": [], "intersheets_ref_own_page": False,
                    "intersheets_ref_prefix": "", "intersheets_ref_short": False,
                    "intersheets_ref_show": False, "intersheets_ref_suffix": "",
                    "junction_size_choice": 3, "label_size_ratio": 0.375,
                    "pin_symbol_size": 25.0, "text_offset_ratio": 0.15},
        "legacy_lib_dir": "", "legacy_lib_list": [], "meta": {"version": 1},
        "net_format_name": "", "ngspice": {}, "page_layout_descr_file": "",
        "plot_directory": "", "spice_current_sheet_as_root": False,
        "spice_external_command": "spice \"%I\"",
        "spice_model_current_sheet_as_root": True, "spice_save_all_currents": False,
        "spice_save_all_dissipations": False, "spice_save_all_voltages": False,
        "subpart_first_id": 65, "subpart_id_separator": 0,
    },
    "sheets": [["<ROOT>", ""]],
    "text_variables": {},
}

if __name__ == "__main__":
    sch = os.path.normpath(os.path.join(HERE, "..", f"{NAME}.kicad_sch"))
    for line in open(sch):
        if line.strip().startswith('(uuid "'):
            PRO["sheets"] = [[line.split('"')[1], ""]]
            break
    out = os.path.normpath(os.path.join(HERE, "..", f"{NAME}.kicad_pro"))
    json.dump(PRO, open(out, "w"), indent=2)
    print("wrote", out)
