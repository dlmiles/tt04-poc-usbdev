`default_nettype none
`timescale 1ns/1ps

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

`define UIO_OE_INPUT   1'b0
`define UIO_OE_OUTPUT  1'b1
    localparam UIO_OE_INPUT = `UIO_OE_INPUT;
    localparam UIO_OE_OUTPUT = `UIO_OE_OUTPUT;

    wire rst;
    assign rst = !rst_n;

    reg phyCd_clk;
    reg phyCd_reset;
    reg phyCd_resetNext;
    reg [1:0] phyCd_counter;
    wire phyCd_counter_overflow;
    assign phyCd_counter_overflow = phyCd_counter == 2'b11;

    // Simulates a PHY clock as synchronous with CLK divided by 4
    // Needs to be 48 MHz
    // Provides the clock domain a reset signal based on our rst_n
    always @(posedge clk or posedge rst) begin
        if (rst) begin
            phyCd_reset <= 1'b0;	// Forces rising edge for reset
            phyCd_resetNext <= 1'b1;
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

    wire usb_dm_read;
    wire usb_dm_write;
    wire usb_dm_writeEnable;
    assign usb_dm_read = uio_in[0];
    assign uio_out[0] = usb_dm_write;
    assign uio_oe[0] = usb_dm_writeEnable;	// UIO 0: bidi: Data-

    wire usb_dp_read;
    wire usb_dp_write;
    wire usb_dp_writeEnable;
    assign usb_dp_read = uio_in[1];
    assign uio_out[1] = usb_dp_write;
    assign uio_oe[1] = usb_dp_writeEnable;	// UIO 1: bidi: Data+

    wire interrupts;
    assign uio_out[2] = interrupts;
    //assign uio_oe[2] = UIO_OE_OUTPUT;		// UIO 2: output: interrupts
    wire wb_WE;
    assign wb_WE = uio_in[2];
    assign uio_out[2] = 1'b0;	// N/C
    assign uio_oe[2] = UIO_OE_INPUT;		// UIO 2: input: wb_WE

    wire power;
    assign power = uio_in[3];
    assign uio_out[3] = 1'b0;	// N/C
    assign uio_oe[3] = UIO_OE_INPUT;		// UIO 3: input: power


    // This wiring is just to make sure nothing gets pruned from the design

    wire [3:0] wb_SEL;
    assign wb_SEL = {uio_in[4],uio_in[4],uio_in[4],uio_in[4]};
    assign uio_out[4] = 1'b0;	// N/C
    assign uio_oe[4] = UIO_OE_INPUT;		// UIO 4: input: wb_SEL

    wire wb_CYC;
    assign wb_CYC = uio_in[5];
    assign uio_out[5] = 1'b0;	// N/C
    assign uio_oe[5] = UIO_OE_INPUT;		// UIO 5: input: wb_CYC

    wire wb_STB;
    assign wb_STB = uio_in[6];
    assign uio_out[6] = 1'b0;	// N/C
    assign uio_oe[6] = UIO_OE_INPUT;		// UIO 6: input: wb_STB

    wire wb_ACK;
    assign uio_out[7] = wb_ACK;
    assign uio_oe[7] = UIO_OE_OUTPUT;		// UIO 7: output: wb_ACK

    wire [13:0] wb_ADR;
    assign wb_ADR[ 0] = ui_in[0];
    assign wb_ADR[ 1] = ui_in[1];
    assign wb_ADR[ 2] = ui_in[2];
    assign wb_ADR[ 3] = ui_in[3];
    assign wb_ADR[ 4] = ui_in[4];
    assign wb_ADR[ 5] = ui_in[5];
    assign wb_ADR[ 6] = ui_in[6];
    assign wb_ADR[ 7] = ui_in[7];
    assign wb_ADR[ 8] = ui_in[0] ^ ui_in[2];
    assign wb_ADR[ 9] = ui_in[1] ^ ui_in[4];
    assign wb_ADR[10] = ui_in[2] ^ ui_in[6];
    assign wb_ADR[11] = ui_in[3] ^ ui_in[0];
    assign wb_ADR[12] = ui_in[4] ^ ui_in[3];
    assign wb_ADR[13] = ui_in[5] ^ ui_in[7];
    
    wire [31:0] wb_DAT_MISO;
    assign uo_out[0] = wb_DAT_MISO[0] ^ wb_DAT_MISO[ 8] ^ wb_DAT_MISO[16] ^ wb_DAT_MISO[24];
    assign uo_out[1] = wb_DAT_MISO[1] ^ wb_DAT_MISO[ 9] ^ wb_DAT_MISO[17] ^ wb_DAT_MISO[25];
    assign uo_out[2] = wb_DAT_MISO[2] ^ wb_DAT_MISO[10] ^ wb_DAT_MISO[18] ^ wb_DAT_MISO[26];
    assign uo_out[3] = wb_DAT_MISO[3] ^ wb_DAT_MISO[11] ^ wb_DAT_MISO[19] ^ wb_DAT_MISO[27];
    assign uo_out[4] = wb_DAT_MISO[4] ^ wb_DAT_MISO[12] ^ wb_DAT_MISO[20] ^ wb_DAT_MISO[28];
    assign uo_out[5] = wb_DAT_MISO[5] ^ wb_DAT_MISO[13] ^ wb_DAT_MISO[21] ^ wb_DAT_MISO[29];
    assign uo_out[6] = wb_DAT_MISO[6] ^ wb_DAT_MISO[14] ^ wb_DAT_MISO[22] ^ wb_DAT_MISO[30];
    assign uo_out[7] = wb_DAT_MISO[7] ^ wb_DAT_MISO[15] ^ wb_DAT_MISO[23] ^ wb_DAT_MISO[31];

    wire [31:0] wb_DAT_MOSI;
    assign wb_DAT_MOSI[ 0] = ui_in[0];
    assign wb_DAT_MOSI[ 1] = ui_in[1];
    assign wb_DAT_MOSI[ 2] = ui_in[2];
    assign wb_DAT_MOSI[ 3] = ui_in[3];
    assign wb_DAT_MOSI[ 4] = ui_in[4];
    assign wb_DAT_MOSI[ 5] = ui_in[5];
    assign wb_DAT_MOSI[ 6] = ui_in[6];
    assign wb_DAT_MOSI[ 7] = ui_in[7];
    assign wb_DAT_MOSI[ 8] = ui_in[0] ^ ui_in[1];
    assign wb_DAT_MOSI[ 9] = ui_in[1] ^ ui_in[2];
    assign wb_DAT_MOSI[10] = ui_in[2] ^ ui_in[3];
    assign wb_DAT_MOSI[11] = ui_in[3] ^ ui_in[4];
    assign wb_DAT_MOSI[12] = ui_in[4] ^ ui_in[5];
    assign wb_DAT_MOSI[13] = ui_in[5] ^ ui_in[6];
    assign wb_DAT_MOSI[14] = ui_in[6] ^ ui_in[7];
    assign wb_DAT_MOSI[15] = ui_in[7] ^ ui_in[0];
    assign wb_DAT_MOSI[16] = ui_in[0] ^ ui_in[2];
    assign wb_DAT_MOSI[17] = ui_in[1] ^ ui_in[3];
    assign wb_DAT_MOSI[18] = ui_in[2] ^ ui_in[4];
    assign wb_DAT_MOSI[19] = ui_in[3] ^ ui_in[5];
    assign wb_DAT_MOSI[20] = ui_in[4] ^ ui_in[6];
    assign wb_DAT_MOSI[21] = ui_in[5] ^ ui_in[7];
    assign wb_DAT_MOSI[22] = ui_in[6] ^ ui_in[0];
    assign wb_DAT_MOSI[23] = ui_in[7] ^ ui_in[1];
    assign wb_DAT_MOSI[24] = ui_in[0] ^ ui_in[4];
    assign wb_DAT_MOSI[25] = ui_in[1] ^ ui_in[5];
    assign wb_DAT_MOSI[26] = ui_in[2] ^ ui_in[6];
    assign wb_DAT_MOSI[27] = ui_in[3] ^ ui_in[7];
    assign wb_DAT_MOSI[28] = ui_in[4] ^ ui_in[0];
    assign wb_DAT_MOSI[29] = ui_in[5] ^ ui_in[1];
    assign wb_DAT_MOSI[30] = ui_in[6] ^ ui_in[2];
    assign wb_DAT_MOSI[31] = ui_in[7] ^ ui_in[3];

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
