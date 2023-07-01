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
 * uio_out[7:5] = CMD input bits
 * uio_out[4]   = valid output bits (signal the bus transction completed)
 * uio_out[3:0] = unused, free for project use
 *
 */
module tt04_to_wishbone (
    input			clk,
    input			rst_n,
    input			ena,

    output		[7:0]	uo_out,
    input		[7:0]	ui_in,

    output		[7:0]	uio_out,
    input		[7:0]	uio_in,
    output		[7:0]	uio_oe,

    /* wishbone master interface presentation */
    output			wb_CYC,
    output			wb_STB,
    input			wb_ACK,
    output			wb_WE,
    /* wb_ADR - MSB 14-bits of 16-bits byte-address as we only support 32bit
     *          aligned access with the bottom 2 bits implicitly zero and
     *          is not represented in the width here. */
    output		[13:0]  wb_ADR,
    input		[31:0]  wb_DAT_MISO,
    output		[31:0]  wb_DAT_MOSI,
    /* wb_SEL - We only support 32-bit aligned access so this byte-wide write-mask
     *          is connected to wb_WE. */
    output		[3:0]   wb_SEL
);

    localparam UIO_OE_INPUT = `UIO_OE_INPUT;
    localparam UIO_OE_OUTPUT = `UIO_OE_OUTPUT;

    // 3 bits of command word
    localparam CMD_IDLE  = 3'b000;
    localparam CMD_EXEC  = 3'b001;
    localparam CMD_AD0   = 3'b010;
    localparam CMD_AD1   = 3'b011;
    localparam CMD_DO0   = 3'b100;
    localparam CMD_DO3   = 3'b101;
    localparam CMD_DI0   = 3'b110;
    localparam CMD_DI3   = 3'b111;

    reg [13:0] ADR;
    reg [31:0] DO;
    reg [31:0] DI;
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

    wire [5:0] action;
    assign action = {cmd_last, cmd};

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

    wire exe_reset;
    assign exe_reset = do_exec && in8 == EXE_RESET;
    wire exe_read;
    assign exe_read = do_exec && in8 == EXE_READ;
    wire exe_write;
    assign exe_write = do_exec && in8 == EXE_WRITE;

    always @(posedge clk) begin
        if (!rst_n || exe_reset) begin	// sync reset
            ADR <= 0;
            DO <= 0;
            DI <= 0;
            cmd_last <= CMD_IDLE;
            pos <= 0;
        end
    end

    always @(posedge clk) begin
        if (!rst_n || exe_reset) begin
            valid <= 0;
        end else if (!do_idle && !exe_read && !exe_write) begin
            valid <= 0;
        end else if (issue && wb_ACK) begin
            valid <= 1;
        end
    end

    // We want a matrix of cmd/last_cmd
    localparam EXE_RESET   = 8'h01;
    localparam EXE_DISABLE = 8'h04;
    localparam EXE_ENABLE  = 8'h05;
    localparam EXE_READ    = 8'h06;
    localparam EXE_WRITE   = 8'h07;

    always @(posedge clk) begin
        if (!rst_n || exe_reset) begin
            WE <= 0;
            CYC <= 0;
            STB <= 0;
            issue <= 0;
        end else if (do_exec) begin
            case (in8)
            EXE_RESET  : begin	// use exe_reset
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
        end else if (!do_idle) begin
            issue <= 0;
        end
        if (wb_ACK) begin
            WE <= 0;
            DI <= wb_DAT_MISO;
            STB <= 0;
        end
    end

    always @(posedge clk) begin
        if (do_ad0) begin
            if (cmd_last == CMD_AD0) begin
                if (pos[0])
                    ADR[8 +: 8] <= in8;
                else
                    ADR[0 +: 8] <= in8;
                pos <= pos + 1;
            end else begin
                ADR[0 +: 8] <= in8;	// pos=0
                pos <= 1;
            end
        end
    end

    always @(posedge clk) begin
        if (do_ad1) begin
            if (cmd_last == CMD_AD1) begin
                if (pos[0])
                    ADR[8 +: 8] <= in8;
                else
                    ADR[0 +: 8] <= in8;
                pos <= pos - 1;
            end else begin
                ADR[8 +: 8] <= in8;	// pos=1
                pos <= 0;
            end
        end
    end

    always @(posedge clk) begin
        if (do_do0) begin
            if (cmd_last == CMD_DO0) begin
                if (pos == 2'd0)
                    DO[0 +: 8] <= in8;
                else if (pos == 2'd1)
                    DO[8 +: 8] <= in8;
                else if (pos == 2'd2)
                    DO[16 +: 8] <= in8;
                else /*if (pos == 2'd3)*/
                    DO[24 +: 8] <= in8;
                pos <= pos + 1;
            end else begin
                DO[0 +: 8] <= in8;	// pos=1
                pos <= 1;
            end
        end
    end

    always @(posedge clk) begin
        if (do_do3) begin
            if (cmd_last == CMD_DO3) begin
                if (pos == 2'd0)
                    DO[0 +: 8] <= in8;
                else if (pos == 2'd1)
                    DO[8 +: 8] <= in8;
                else if (pos == 2'd2)
                    DO[16 +: 8] <= in8;
                else /*if (pos == 2'd3)*/
                    DO[24 +: 8] <= in8;
                pos <= pos - 1;
            end else begin
                DO[24 +: 8] <= in8;	// pos=3
                pos <= 2;
            end
        end
    end

    always @(posedge clk) begin
        if (do_di0) begin
            if (cmd_last == CMD_DI0) begin
                if (pos == 2'd0)
                    out8 <= DI[0 +: 8];
                else if (pos == 2'd1)
                    out8 <= DI[8 +: 8];
                else if (pos == 2'd2)
                    out8 <= DI[16 +: 8];
                else /*if (pos == 2'd3)*/
                    out8 <= DI[24 +: 8];
                pos <= pos + 1;
            end else begin
                // We expose DI[7:0] by default, CMD_DI0 will send with DI[15:8]
                out8 <= DI[8 +: 8];	// pos=1
                pos <= 2;
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
                pos <= pos - 1;
            end else begin
                out8 <= DI[24 +: 8];	// pos=3
                pos <= 2;
            end
        end else begin
            out8 = DI[0 +: 8]; // 8'bxxxxxxxx; debugging
        end
    end

    assign wb_CYC = CYC;
    assign wb_STB = STB;
    assign wb_WE = WE;
    assign wb_SEL[3:0] = {WE,WE,WE,WE};
    assign wb_ADR[13:0] = ADR;
    assign wb_DAT_MOSI[31:0] = DO;

    always @(posedge clk) begin
       cmd_last <= cmd;
    end

endmodule
