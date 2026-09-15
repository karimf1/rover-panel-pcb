# rover-panel-supervisor hardware build.
#
# Everything in hw/ except this Makefile, the two library tables and gen/ is
# GENERATED. Edit the scripts in gen/ (or design/spec.py, or the panel's
# params.py), not the .kicad_sch or .kicad_pcb -- a regeneration overwrites them.
#
#   make            library, schematic, netlist, board, then every check
#   make check      design maths, ERC, DRC (with schematic parity),
#                   interlock proof, layout rules, fit against the panel
#   make fab        gerbers, drill, BOM, placement -- what you send the fab
#   make docs       schematic PDF, board SVGs and a 3D render for the README
#   make clean      remove generated artefacts
#
# The board is only ever as current as the panel: `make interface` re-exports
# panel_interface.json from ../../rover-power-panel/scripts/params.py, and
# `make fit` fails if the JSON and params.py disagree.

KICAD ?= /Applications/KiCad/KiCad.app/Contents
CLI   ?= $(KICAD)/MacOS/kicad-cli
# pcbnew (and numpy for the router) come from KiCad's own interpreter
KPY   ?= $(KICAD)/Frameworks/Python.framework/Versions/3.9/bin/python3
PY    ?= python3
Q     = 2>/dev/null

NAME   = rover-panel-supervisor
SCH    = $(NAME).kicad_sch
PCB    = $(NAME).kicad_pcb
NET    = $(NAME).net
PRO    = $(NAME).kicad_pro
LIB    = lib/$(NAME).kicad_sym
IFACE  = ../design/panel_interface.json
PANEL  = ../../rover-power-panel/scripts
FABDIR = fab

.PHONY: all check design erc drc interlock layout fit fab docs clean interface

all: $(PCB) check

# ---------------------------------------------------------------- generation
interface:
	cd $(PANEL) && $(PY) params.py --export-pcb

$(LIB): gen/gen_lib.py ../design/spec.py
	$(PY) gen/gen_lib.py

$(SCH): gen/gen_sch.py gen/kisch.py gen/symlib.py gen/sexp.py $(LIB) ../design/spec.py
	$(PY) gen/gen_sch.py

$(NET): $(SCH)
	$(CLI) sch export netlist --format kicadsexpr -o $(NET) $(SCH) $(Q)

# gen_pro.py runs AFTER gen_pcb.py: pcbnew's SaveBoard rewrites the project
# file with defaults and silently drops the net classes.
$(PCB): gen/gen_pcb.py gen/kipcb.py gen/autoroute.py gen/gen_pro.py $(NET) $(IFACE) \
        ../design/spec.py
	$(KPY) gen/gen_pcb.py
	$(PY) gen/gen_pro.py

$(PRO): $(PCB)

# ------------------------------------------------------------------- checks
check: design erc drc interlock layout fit
	@echo "== all checks passed =="

design:
	@cd ../design && $(PY) test_calcs.py

# --exit-code-violations makes the tool the judge; the grep only reports.
erc: $(SCH) $(PRO)
	@echo "== ERC =="
	@$(CLI) sch erc --severity-all --exit-code-violations -o erc.rpt $(SCH) \
	  >/dev/null 2>&1 || { grep -E '^\s*\*\*' erc.rpt; echo "ERC FAILED"; exit 1; }
	@grep -E '^\s*\*\* ERC messages' erc.rpt

# --schematic-parity also proves the board really is built from this schematic
drc: $(PCB) $(PRO)
	@echo "== DRC (with schematic parity) =="
	@$(CLI) pcb drc --severity-all --schematic-parity --exit-code-violations \
	  --units mm -o drc.rpt $(PCB) >/dev/null 2>&1 \
	  || { grep -E '^\*\* Found' drc.rpt; echo "DRC FAILED"; exit 1; }
	@grep -E '^\*\* Found' drc.rpt

interlock: $(NET)
	@$(PY) gen/check_interlock.py
	@$(PY) gen/test_interlock_check.py

layout: $(PCB)
	@$(KPY) gen/check_layout.py $(Q)

fit: $(PCB)
	@$(KPY) gen/check_fit.py $(Q)

# --------------------------------------------------------------- fab output
fab: $(PCB) $(SCH)
	@mkdir -p $(FABDIR)
	$(CLI) pcb export gerbers --no-protel-ext -o $(FABDIR)/ $(PCB) $(Q)
	$(CLI) pcb export drill --format excellon --drill-origin absolute \
	  --excellon-separate-th -o $(FABDIR)/ $(PCB) $(Q)
	$(CLI) pcb export pos --format csv --units mm --side both \
	  -o $(NAME)-placement.csv $(PCB) $(Q)
	$(CLI) sch export bom --fields 'Reference,Value,Footprint,MPN,$${QUANTITY},$${DNP}' \
	  --group-by Value,Footprint --labels 'Refs,Value,Footprint,MPN,Qty,DNP' \
	  --exclude-dnp -o $(NAME)-bom.csv $(SCH) $(Q)
	cp $(NAME)-bom.csv $(NAME)-placement.csv $(FABDIR)/
	cd $(FABDIR) && zip -q -FS ../$(NAME)-fab.zip *.g* *.drl *.csv 2>/dev/null || true
	@echo "fab package: $(NAME)-fab.zip"

# --------------------------------------------------------------------- docs
docs: $(PCB) $(SCH)
	@mkdir -p ../docs/img
	$(CLI) sch export pdf -o ../docs/$(NAME)-schematic.pdf $(SCH) $(Q)
	$(CLI) pcb export svg --layers 'F.Cu,F.SilkS,F.Mask,Edge.Cuts' \
	  --page-size-mode 2 --exclude-drawing-sheet -o ../docs/img/board-top.svg $(PCB) $(Q)
	$(CLI) pcb export svg --layers 'B.Cu,Edge.Cuts' --page-size-mode 2 \
	  --exclude-drawing-sheet --mirror -o ../docs/img/board-bottom.svg $(PCB) $(Q)
	$(CLI) pcb render --side top --width 2200 --height 1000 --zoom 2.1 --quality high \
	  -o ../docs/img/board-3d.png $(PCB) $(Q)
	@echo "docs in ../docs/"

clean:
	rm -f $(SCH) $(PCB) $(NET) $(PRO) $(LIB) erc.rpt drc.rpt \
	      $(NAME)-fab.zip $(NAME)-bom.csv $(NAME)-placement.csv
	rm -rf $(FABDIR) .debug
