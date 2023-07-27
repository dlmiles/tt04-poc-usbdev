`default_nettype none
`timescale 1ns/1ps

`include "config.vh"

module tb_usbdev (
    //input			clk,
    //input			rst_n,	// async (verilator needed reg)
    //input			ena,

    output		[7:0]	uo_out,
    //input		[7:0]	ui_in,

    output		[7:0]	uio_out,
    //input		[7:0]	uio_in,
    output		[7:0]	uio_oe
);
`ifndef SYNTHESIS
    reg [(8*32)-1:0] DEBUG;
    reg DEBUG_wire;
`endif

    reg clk;
    reg rst_n;
    reg ena;

    reg [7:0] ui_in;
    reg [7:0] uio_in;

`ifdef PHY_CLOCK_EXTERNAL
    reg phy_clk;		// alias for POWERBIT
    assign uio_in[3] = phy_clk;	// i: power
`endif

    initial begin
        //$dumpfile ("tb_usbdev.vcd");
        $dumpfile ("tb.vcd");	// Renamed for GHA
`ifdef GL_TEST
        // the internal state of a flattened verilog is not that interesting
        $dumpvars (1, tb_usbdev);
`else
        $dumpvars (0, tb_usbdev);
`endif
`ifdef TIMING
        #1;
`endif
`ifndef SYNTHESIS
        DEBUG = {8'h44, 8'h45, 8'h42, 8'h55, 8'h47, {27{8'h20}}}; // "DEBUG        "
        DEBUG_wire = 0;
`endif
    end


    tt_um_dlmiles_tt04_poc_usbdev dut (
`ifdef USE_POWER_PINS
        .VPWR     ( 1'b1),
        .VGND     ( 1'b0),
`endif
`ifdef USE_POWER_PINS_LEGACY
        .vccd1    ( 1'b1),
        .vssd1    ( 1'b0),
`endif
        .clk      (clk),
        .rst_n    (rst_n),
        .ena      (ena),
        .uo_out   (uo_out),
        .ui_in    (ui_in),
        .uio_out  (uio_out),
        .uio_in   (uio_in),
        .uio_oe   (uio_oe)
    );

endmodule
