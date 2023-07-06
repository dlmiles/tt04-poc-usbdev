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
);
`ifndef SYNTHESIS
    reg [(8*32)-1:0] DEBUG;
    reg DEBUG_wire;
`endif

    initial begin
        //$dumpfile ("tb_usbdev.vcd");
        $dumpfile ("tb.vcd");	// Renamed for GHA
        $dumpvars (0, tb_usbdev);
        #1;
        
        DEBUG <= {8'h44, 8'h45, 8'h42, 8'h55, 8'h47, {27{8'h20}}}; // "DEBUG        "
        DEBUG_wire <= 0;
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
    );

endmodule
