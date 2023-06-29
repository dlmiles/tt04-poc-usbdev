`default_nettype none
`timescale 1ns/1ps

module tb_usbdev (
    input			clk,
    input			rst_n,
    input			ena,

    output		[7:0]	uo_out,
    input		[7:0]	ui_in,

    output		[7:0]	uio_out,
    input		[7:0]	uio_in,
    output		[7:0]	uio_oe

`ifdef COCOTB_SIM
`ifndef GL_TEST
    , input			sim_reset
`endif
`endif
);

    initial begin
        $dumpfile ("tb_usbdev.vcd");
        $dumpvars (0, tb_usbdev);
        #1;
    end

    tt_um_dlmiles_tt04_poc_usbdev dut (
`ifdef GL_TEST
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
`ifdef COCOTB_SIM
`ifndef GL_TEST
     , .sim_reset (sim_reset)
`endif
`endif
    );

endmodule
