# Makefile
# See https://docs.cocotb.org/en/stable/quickstart.html for more info

# defaults
SIM ?= icarus
TOPLEVEL_LANG ?= verilog

# normal simulation
ifneq ($(GATES),yes)

# this is the only part you should need to modify:
VERILOG_SOURCES += $(PWD)/tbc_tt_um_dlmiles_tt04_poc_usbdev.v
VERILOG_SOURCES += $(PWD)/top_tt_um_dlmiles_tt04_poc_usbdev.v
VERILOG_SOURCES += $(PWD)/tt04_to_wishbone.v
VERILOG_SOURCES += $(PWD)/UsbDeviceTop.v

else

# gate level simulation requires some extra setup, you shouldn't need to touch this
COMPILE_ARGS    += -DGL_TEST
COMPILE_ARGS    += -DFUNCTIONAL
COMPILE_ARGS    += -DUSE_POWER_PINS
COMPILE_ARGS    += -DSIM
COMPILE_ARGS    += -DUNIT_DELAY=\#1
#VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/primitives.v
#VERILOG_SOURCES += $(PDK_ROOT)/sky130A/libs.ref/sky130_fd_sc_hd/verilog/sky130_fd_sc_hd.v
VERILOG_SOURCES += sky130_fd_sc_hd/primitives.v
VERILOG_SOURCES += sky130_fd_sc_hd/sky130_fd_sc_hd.v

# this gets copied in by the GDS action workflow
VERILOG_SOURCES += $(PWD)/tbc_tt_um_dlmiles_tt04_poc_usbdev.v $(PWD)/gate_level_netlist.v
endif

ifeq ($(SIM),icarus)
COMPILE_ARGS    += -DTIMING
endif

ifeq ($(SIM),verilator)
EXTRA_ARGS += -Wno-WIDTHTRUNC
EXTRA_ARGS += --trace --trace-structs --no-timing

ifeq ($(COVERAGE),yes)
EXTRA_ARGS += --coverage --coverage-underscore
endif

ifeq ($(RANDOM_POLICY),zero)
PLUSARGS += +verilator+rand+reset+0
else ifeq ($(RANDOM_POLICY),one)
PLUSARGS += +verilator+rand+reset+1
else ifeq ($(RANDOM_POLICY),random)
PLUSARGS += +verilator+rand+reset+2
endif
endif

# TOPLEVEL is the name of the toplevel module in your Verilog or VHDL file
TOPLEVEL = tb_usbdev

# MODULE is the basename of the Python test file
MODULE = test_usbdev

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim
