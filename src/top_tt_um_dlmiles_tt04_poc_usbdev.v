`default_nettype none
`timescale 1ns/1ps

`include "tt_um.vh"

module tt_um_dlmiles_tt04_poc_usbdev (
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

    localparam UIO_OE_INPUT = `UIO_OE_INPUT;
    localparam UIO_OE_OUTPUT = `UIO_OE_OUTPUT;

    wire rst;
    assign rst = !rst_n;	// We are a sync-reset module

    reg phyCd_clk;
    reg phyCd_reset;
    reg phyCd_resetNext;
    reg [1:0] phyCd_counter;
    wire phyCd_counter_overflow;
    assign phyCd_counter_overflow = phyCd_counter == 2'b01;

    // Simulates a PHY clock as synchronous with CLK divided by 4
    // Needs to be 48 MHz
    // Provides the clock domain a sync-reset signal based on our rst_n
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            phyCd_reset <= 1'b0;	// Forces observable rising edge for reset after the clock
            phyCd_resetNext <= 1'b1;	// has run at least once for each edge in the other clock domain
            phyCd_clk <= 1'b0;
            phyCd_counter <= 2'b00;
        end else if (phyCd_counter_overflow) begin
            if (phyCd_clk) begin
                phyCd_reset <= phyCd_resetNext;
                phyCd_resetNext <= 1'b0;
            end
            phyCd_clk <= ~phyCd_clk;
            phyCd_counter <= phyCd_counter + 1;
        end else begin
            phyCd_counter <= phyCd_counter + 1;
        end
    end

    wire usb_dp_read;
    wire usb_dp_write;
    wire usb_dp_writeEnable;
    assign usb_dp_read = uio_in[0];
    assign uio_out[0] = usb_dp_write;
    assign uio_oe[0] = usb_dp_writeEnable;	// UIO 0: bidi: Data+

    wire usb_dm_read;
    wire usb_dm_write;
    wire usb_dm_writeEnable;
    assign usb_dm_read = uio_in[1];
    assign uio_out[1] = usb_dm_write;
    assign uio_oe[1] = usb_dm_writeEnable;	// UIO 1: bidi: Data-

    wire interrupts;
    assign uio_out[2] = interrupts;
    assign uio_oe[2] = UIO_OE_OUTPUT;		// UIO 2: output: interrupts (disabled)

    wire power;
    assign power = uio_in[3];
    assign uio_out[3] = 1'b0;	// N/C tie-down
    assign uio_oe[3] = UIO_OE_INPUT;		// UIO 3: input: power


    wire wb_CYC;
    wire wb_STB;
    wire wb_ACK;
    wire wb_WE;
    wire [3:0] wb_SEL;
    wire [13:0] wb_ADR;
    wire [31:0] wb_DAT_MISO;
    wire [31:0] wb_DAT_MOSI;

    // This is slicing off the top 4 bits while ignoring the bottom 4 bits
    // Otherwise even through the bottom 4 bits are not connected inside tt2wb we get error
    wire [7:0] uio_oe_tmp;
    assign uio_oe[7:4] = uio_oe_tmp[7:4];
    wire [7:0] uio_out_tmp;
    assign uio_out[7:4] = uio_out_tmp[7:4];

    tt04_to_wishbone tt2wb (
        .clk                (clk),                      //i
        .rst_n              (rst_n),                    //i
        .ena                (ena),                      //i

        .uo_out             (uo_out),                   //o
        .ui_in              (ui_in),                    //i
        .uio_out            (uio_out_tmp),              //o
        .uio_in             (uio_in),                   //i
        .uio_oe             (uio_oe_tmp),               //o

        .wb_CYC             (wb_CYC),			//o
        .wb_STB             (wb_STB),			//o
        .wb_ACK             (wb_ACK),			//i
        .wb_WE              (wb_WE),			//o
        .wb_ADR		    (wb_ADR),			//o
        .wb_DAT_MISO        (wb_DAT_MISO),		//i
        .wb_DAT_MOSI        (wb_DAT_MOSI),		//o
        .wb_SEL             (wb_SEL)			//o
    );

    UsbDeviceTop usbdev (
        .wb_CYC             (wb_CYC),			//i
        .wb_STB             (wb_STB),			//i
        .wb_ACK             (wb_ACK),			//o
        .wb_WE              (wb_WE),			//i
        .wb_ADR		    (wb_ADR),			//i
        .wb_DAT_MISO        (wb_DAT_MISO),		//o
        .wb_DAT_MOSI        (wb_DAT_MOSI),		//i
        .wb_SEL             (wb_SEL),			//i
        .usb_dp_read        (usb_dp_read),		//i
        .usb_dp_write       (usb_dp_write),		//o
        .usb_dp_writeEnable (usb_dp_writeEnable),	//o
        .usb_dm_read        (usb_dm_read),		//i
        .usb_dm_write       (usb_dm_write),		//o
        .usb_dm_writeEnable (usb_dm_writeEnable),	//o
        .power              (power),			//i
        .interrupts         (interrupts),		//o
        .ctrlCd_clk         (clk),			//i
        .ctrlCd_reset       (rst),			//i
        .phyCd_clk          (phyCd_clk),		//i PHY ClockDomain clock
        .phyCd_reset        (phyCd_reset)		//i PHY ClockDomain reset (sync)
    );

endmodule
