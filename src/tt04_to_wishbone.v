`default_nettype none
`timescale 1ns/1ps

`include "tt_um.vh"

/*
 * This is a method of implementing a wishbone master interface inside a user tt project.
 *
 * It is expected to be manipulated under CPU control and processes wishbone classic transactions.
 *
 * This will leave only 4 bits uio_xxx[3:0] unallocated.
 *
 * uio_out[3:0] = unused, free for project use
 * uio_out[4]   = OUTPUT valid output bits (signal the bus transction completed)
 * uio_out[7:5] = INPUT  CMD input bits
 * ui_in[7:0]   = INPUT  all in use
 * uo_out[7:0]  = OUTPUT all in use
 *
 */
module tt04_to_wishbone #(
    parameter	DATA_WIDTH	= 32,
                ADDRESS_WIDTH	= 14,
                ADDRESS_ALIGN	= 2,
                SEL_WIDTH	= 4
) (
    input			clk,
    input			rst_n,
    input			ena,

    output		[7:0]	uo_out,
    input		[7:0]	ui_in,

    output		[7:0]	uio_out,
    input		[7:0]	uio_in,
    output		[7:0]	uio_oe,

    /* wishbone master interface presentation */
    output					wb_CYC,
    output					wb_STB,
    input					wb_ACK,
    output					wb_WE,
    /* wb_ADR - MSB 14-bits of 16-bits byte-address as we only support 32bit
     *          aligned access with the bottom 2 bits implicitly zero and
     *          is not represented in the width here.
     */
    output		[ADDRESS_WIDTH-1:0]	wb_ADR,
    input		[DATA_WIDTH-1:0]	wb_DAT_MISO,
    output		[DATA_WIDTH-1:0]	wb_DAT_MOSI,
    /* wb_SEL - We only support 32-bit aligned access.
     *          Use EXE_WBSEL to control this byte-write-mask.
     */
    output		[SEL_WIDTH-1:0]		wb_SEL
);

    localparam UIO_OE_INPUT = `UIO_OE_INPUT;
    localparam UIO_OE_OUTPUT = `UIO_OE_OUTPUT;

    localparam FULL_ADDRESS_WIDTH = ADDRESS_WIDTH + ADDRESS_ALIGN;

    // 3 bits of command word
    localparam CMD_IDLE  = 3'b000;
    localparam CMD_EXEC  = 3'b001;
    localparam CMD_AD0   = 3'b010;
    localparam CMD_AD1   = 3'b011;
    localparam CMD_DO0   = 3'b100;	// master data out (towards tt_um module)
    localparam CMD_DO3   = 3'b101;
    localparam CMD_DI0   = 3'b110;	// master data in (away from tt_um module)
    localparam CMD_DI3   = 3'b111;

    reg [FULL_ADDRESS_WIDTH-1:0] ADR;	// expecting bottom 2 bits to be dropped by flow as output not connected
    reg [DATA_WIDTH-1:0] DO;
    reg [DATA_WIDTH-1:0] DI;
    reg [SEL_WIDTH-1:0] SEL;
    reg CYC;
    reg STB;	// aka bus active
    reg WE;

    wire [2:0] cmd;
    assign cmd = uio_in[7:5];
    reg valid;
    assign uio_out[4] = valid;
    assign uio_out[5] = 0; // N/C tie-down
    assign uio_out[6] = 0; // N/C tie-down
    assign uio_out[7] = 0; // N/C tie-down
    assign uio_oe[4] = UIO_OE_OUTPUT;
    assign uio_oe[5] = UIO_OE_INPUT;
    assign uio_oe[6] = UIO_OE_INPUT;
    assign uio_oe[7] = UIO_OE_INPUT;
    reg issue;		// this stop repeating bus transation

    wire [7:0] in8;
    assign in8 = ui_in[7:0];
    reg [7:0] out8;
    assign uo_out[7:0] = out8;

    reg [2:0] cmd_last;
    reg [1:0] pos;
    //reg [1:0] pos_next;	// placeholder expect pruned out

    wire do_idle;
    assign do_idle = cmd == CMD_IDLE;
    wire do_exec;
    assign do_exec = cmd == CMD_EXEC;
    wire do_ad0;
    assign do_ad0 = cmd == CMD_AD0;
    wire do_ad1;
    assign do_ad1 = cmd == CMD_AD1;
    wire do_do0;
    assign do_do0 = cmd == CMD_DO0;
    wire do_do3;
    assign do_do3 = cmd == CMD_DO3;
    wire do_di0;
    assign do_di0 = cmd == CMD_DI0;
    wire do_di3;
    assign do_di3 = cmd == CMD_DI3;

    wire [2:0] in8_exe;
    assign in8_exe = in8[2:0];
    wire exe_reset;
    assign exe_reset = do_exec && in8_exe == EXE_RESET;
    wire exe_read;
    assign exe_read = do_exec && in8_exe == EXE_READ;
    wire exe_write;
    assign exe_write = do_exec && in8_exe == EXE_WRITE;

    wire reset;
    assign reset = !rst_n || exe_reset;

    always @(posedge clk) begin
        if (reset) begin
            valid <= 0;
        end else if (!do_idle && !exe_read && !exe_write) begin
            valid <= 0;
        end else if (issue && wb_ACK) begin
            valid <= 1;
        end
    end

    localparam EXE_RESET   = 3'h1;
    localparam EXE_WBSEL   = 3'h2;  // needs better testing
    localparam EXE_DISABLE = 3'h4;
    localparam EXE_ENABLE  = 3'h5;
    localparam EXE_READ    = 3'h6;
    localparam EXE_WRITE   = 3'h7;

    always @(posedge clk) begin
        if (reset) begin
            DI <= 0;
            WE <= 0;
            CYC <= 0;
            STB <= 0;
            SEL <= 4'b1111;
            issue <= 0;
        end else if (do_exec) begin
            case (in8_exe)
            EXE_RESET  : begin	// use exe_reset
            end
            EXE_WBSEL  : begin
                SEL <= in8[7:4];
                issue <= 0;
            end
            EXE_ENABLE  : begin
                CYC <= 1;
                issue <= 0;
            end
            EXE_DISABLE : begin
                CYC <= 0;
                STB <= 0;
                issue <= 0;
            end
            EXE_READ    : begin
                if (!issue) begin
                    WE <= 0;
                    STB <= 1;
                    issue <= 1;
                end
            end
            EXE_WRITE   : begin
                if (!issue) begin
                    WE <= 1;
                    STB <= 1;
                    issue <= 1;
                end
            end
            default  : ;
            endcase
        end else begin
            issue <= 0;
        end
        // We'll add STB with wb_ACK here just in case a bad WB module flashes wb_ACK at us
        if (STB && wb_ACK) begin
            WE <= 0;
            DI <= wb_DAT_MISO;
            STB <= 0;
        end
    end

    always @(posedge clk) begin
        if (reset) begin	// sync reset
            pos <= 0;
        end else begin
            //pos <= pos_next;
            if (do_ad0 && cmd_last == CMD_AD0)
                pos <= pos + 1;
            else if(do_ad0)
                pos <= 1;
            else if (do_ad1 && cmd_last == CMD_AD1)
                pos <= pos - 1;
            else if(do_ad1)
                pos <= 0;
            else if (do_do0 && cmd_last == CMD_DO0)
                pos <= pos + 1;
            else if(do_do0)
                pos <= 1;
            else if (do_do3 && cmd_last == CMD_DO3)
                pos <= pos - 1;
            else if(do_do3)
                pos <= 2;
            else if (do_di0 && cmd_last == CMD_DI0)
                pos <= pos + 1;
            else if(do_di0)
                pos <= 2;
            else if (do_di3 && cmd_last == CMD_DI3)
                pos <= pos - 1;
            else if(do_di3)
                pos <= 2;
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            ADR <= 0;
            //pos_next <= 0;
        end else if (do_ad0) begin
            if (cmd_last == CMD_AD0) begin
                if (pos[0])
                    ADR[8 +: 8] <= in8;
                else
                    ADR[0 +: 8] <= in8;
                //pos_next <= pos + 1;
            end else begin
                ADR[0 +: 8] <= in8;	// pos=0
                //pos_next <= 1;
            end
        end else if (do_ad1) begin
            if (cmd_last == CMD_AD1) begin
                if (pos[0])
                    ADR[8 +: 8] <= in8;
                else
                    ADR[0 +: 8] <= in8;
                //pos_next <= pos - 1;
            end else begin
                ADR[8 +: 8] <= in8;	// pos=1
                //pos_next <= 0;
            end
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            DO <= 0;
        end else if (do_do0) begin
            if (cmd_last == CMD_DO0) begin
                if (pos == 2'd0)
                    DO[0 +: 8] <= in8;
                else if (pos == 2'd1)
                    DO[8 +: 8] <= in8;
                else if (pos == 2'd2)
                    DO[16 +: 8] <= in8;
                else /*if (pos == 2'd3)*/
                    DO[24 +: 8] <= in8;
                //pos_next <= pos + 1;
            end else begin
                DO[0 +: 8] <= in8;	// pos=1
                //pos_next <= 1;
            end
        end else if (do_do3) begin
            if (cmd_last == CMD_DO3) begin
                if (pos == 2'd0)
                    DO[0 +: 8] <= in8;
                else if (pos == 2'd1)
                    DO[8 +: 8] <= in8;
                else if (pos == 2'd2)
                    DO[16 +: 8] <= in8;
                else /*if (pos == 2'd3)*/
                    DO[24 +: 8] <= in8;
                //pos_next <= pos - 1;
            end else begin
                DO[24 +: 8] <= in8;	// pos=3
                //pos_next <= 2;
            end
        end
    end

    always @(posedge clk) begin
        if (reset) begin
            // NOOP
            // Lets see if yosys can see drivers of 'pos' are mutually exclusive states
            //  no it couldn't :( so we reworked the file instead.  See pos_next/pos.
        end else if (do_di0) begin
            if (cmd_last == CMD_DI0) begin
                if (pos == 2'd0)
                    out8 <= DI[0 +: 8];
                else if (pos == 2'd1)
                    out8 <= DI[8 +: 8];
                else if (pos == 2'd2)
                    out8 <= DI[16 +: 8];
                else /*if (pos == 2'd3)*/
                    out8 <= DI[24 +: 8];
                //pos_next <= pos + 1;
            end else begin
                // We expose DI[7:0] by default, CMD_DI0 will send with DI[15:8]
                out8 <= DI[8 +: 8];	// pos=1
                //pos_next <= 2;
            end
        end else if (do_di3) begin
            if (cmd_last == CMD_DI3) begin
                if (pos == 2'd0)
                    out8 <= DI[0 +: 8];
                else if (pos == 2'd1)
                    out8 <= DI[8 +: 8];
                else if (pos == 2'd2)
                    out8 <= DI[16 +: 8];
                else /*if (pos == 2'd3)*/
                    out8 <= DI[24 +: 8];
                //pos_next <= pos - 1;
            end else begin
                out8 <= DI[24 +: 8];	// pos=3
                //pos_next <= 2;
            end
        end else begin
            out8 <= DI[0 +: 8]; // 8'bxxxxxxxx; debugging
        end
    end

    assign wb_CYC = CYC;
    assign wb_STB = STB;
    assign wb_WE = WE;
    assign wb_SEL[SEL_WIDTH-1:0] = WE ? SEL : {SEL_WIDTH{1'b0}};
    assign wb_ADR[ADDRESS_WIDTH-1:0] = ADR[FULL_ADDRESS_WIDTH-1:ADDRESS_ALIGN];
    assign wb_DAT_MOSI[DATA_WIDTH-1:0] = DO;

    always @(posedge clk) begin
        if (reset) begin
            cmd_last <= CMD_IDLE;
        end else begin
            cmd_last <= cmd;
        end
    end

endmodule
