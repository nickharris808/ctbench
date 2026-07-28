// Cross-check testbench: does the ACTUAL RTL behave as the hand-authored z3 relation claims?
//   - euclid_gcd: two secret operand pairs must complete at DIFFERENT cycles (the leak is real in RTL).
//   - ct_gcd:     any secret operand pair must complete at the SAME fixed cycle (constant-time in RTL).
// Prints "DONE <name> <a> <b> <cycle>" lines; a harness (self_compose cross-check) parses them.
`timescale 1ns/1ps
module tb_ct;
    reg clk = 0; always #5 clk = ~clk;

    // ---- euclid_gcd instance ----
    reg e_rst, e_start; reg [7:0] e_a, e_b;
    wire e_done; wire [7:0] e_g;
    euclid_gcd EU (.clk(clk), .rst(e_rst), .start(e_start), .a_in(e_a), .b_in(e_b),
                   .done(e_done), .gcd_out(e_g));

    // ---- ct_gcd instance ----
    reg c_rst, c_start; reg [7:0] c_a, c_b;
    wire c_done; wire [7:0] c_g;
    ct_gcd CT (.clk(clk), .rst(c_rst), .start(c_start), .a_in(c_a), .b_in(c_b),
               .done(c_done), .gcd_out(c_g));

    integer cyc;

    // run one design to completion; returns cycles from start to done via $display
    task run_euclid(input [7:0] a, input [7:0] b);
        begin
            @(negedge clk); e_rst=1; e_start=0; e_a=0; e_b=0;
            @(negedge clk); e_rst=0; e_start=1; e_a=a; e_b=b;
            @(negedge clk); e_start=0; cyc=1;
            while (!e_done && cyc < 300) begin @(negedge clk); cyc=cyc+1; end
            $display("DONE euclid_gcd %0d %0d %0d", a, b, cyc);
        end
    endtask

    task run_ct(input [7:0] a, input [7:0] b);
        begin
            @(negedge clk); c_rst=1; c_start=0; c_a=0; c_b=0;
            @(negedge clk); c_rst=0; c_start=1; c_a=a; c_b=b;
            @(negedge clk); c_start=0; cyc=1;
            while (!c_done && cyc < 300) begin @(negedge clk); cyc=cyc+1; end
            $display("DONE ct_gcd %0d %0d %0d", a, b, cyc);
        end
    endtask

    initial begin
        run_euclid(8'd66, 8'd108);   // z3 counterexample pair A
        run_euclid(8'd17, 8'd170);   // z3 counterexample pair B  (must differ from A's cycle)
        run_ct(8'd66, 8'd108);       // constant-time: fixed cycle
        run_ct(8'd17, 8'd170);       // constant-time: same fixed cycle
        run_ct(8'd200, 8'd3);        // constant-time: still the same fixed cycle
        $finish;
    end
endmodule
