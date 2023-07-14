# PLEASE DO NOT EDIT THIS FILE!
# If you get stuck with this config, please open an issue or get in touch via the discord.

# Configuration docs: https://openlane.readthedocs.io/en/latest/reference/configuration.html

# User config
set script_dir [file dirname [file normalize [info script]]]

# read some user config that is written by the setup.py program.
# - the name of the module is defined
# - the list of source files
source $::env(DESIGN_DIR)/user_config.tcl

# save some time
set ::env(RUN_KLAYOUT_XOR) 0
set ::env(RUN_KLAYOUT_DRC) 0

# don't put clock buffers on the outputs
set ::env(PL_RESIZER_BUFFER_OUTPUT_PORTS) 0

# allow use of specific sky130 cells
set ::env(SYNTH_READ_BLACKBOX_LIB) 1

# reduce wasted space
set ::env(TOP_MARGIN_MULT) 1
set ::env(BOTTOM_MARGIN_MULT) 1
set ::env(LEFT_MARGIN_MULT) 6
set ::env(RIGHT_MARGIN_MULT) 6

# absolute die size
set ::env(FP_SIZING) absolute

set ::env(PL_BASIC_PLACEMENT) {0}
set ::env(GRT_ALLOW_CONGESTION) "1"

# otherwise fails on small designs at global placement
set ::env(GRT_CELL_PADDING) "4"

set ::env(FP_IO_HLENGTH) 2
set ::env(FP_IO_VLENGTH) 2

# use alternative efabless decap cells to solve LI density issue
set ::env(DECAP_CELL) "\
    sky130_fd_sc_hd__decap_3 \
    sky130_fd_sc_hd__decap_4 \
    sky130_fd_sc_hd__decap_6 \
    sky130_fd_sc_hd__decap_8 \
    sky130_ef_sc_hd__decap_12"

# clock
set ::env(RUN_CTS) 1
# period is in ns, so 20ns == 50MHz
#set ::env(CLOCK_PERIOD) "20"
# period is in ns, so 10ns == 100MHz
set ::env(CLOCK_PERIOD) "10"
set ::env(CLOCK_PORT) {clk}

# hold/slack margin
# set ::env(PL_RESIZER_HOLD_SLACK_MARGIN) 0.8 
# set ::env(GLB_RESIZER_HOLD_SLACK_MARGIN) 0.8 

# don't use power rings or met5
set ::env(DESIGN_IS_CORE) 0
set ::env(RT_MAX_LAYER) {met4}


#set ::env(PL_TARGET_DENSITY) 0.75
# FP_CORE_UTIL=50 is the default (will target 60% max util)
# FP_CORE_UTIL=60 will adding +10% to default (70% max util)
#set ::env(FP_CORE_UTIL) 60

# 10 is default
set ::env(SYNTH_MAX_FANOUT) 7

# 25 is default
set ::env(CTS_SINK_CLUSTERING_SIZE) 20

# H / W
set ::env(FP_ASPECT_RATIO) [expr 2/4]
