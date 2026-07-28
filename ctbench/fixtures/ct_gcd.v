// ct_gcd — fixed-iteration (constant-time) GCD. `done` is a function ONLY of a cycle counter `iter`
// that advances unconditionally while running, so completion time is FIXED (K cycles) regardless of the
// secret operands — i.e. the timing observable is data-oblivious. The datapath still reduces the secret
// operands into `gcd_out` (so the property is NON-vacuous: the secret flows to the result, just not to
// the timing). This is the positive design: self-composition PROVES timing non-interference, and the
// refutation is independently re-checked.
//
// Interface mirrors the self-composition transition relation for the `ct_gcd` benchmark.
module ct_gcd (clk, rst, start, a_in, b_in, done, gcd_out);
    parameter K = 5'd16;                 // fixed number of reduction cycles

    input             clk, rst, start;
    input      [7:0]  a_in, b_in;        // SECRET operands
    output            done;
    output     [7:0]  gcd_out;

    reg  [7:0] a, b;
    reg  [4:0] iter;
    reg        running;

    // done depends ONLY on `iter` and `running` (control), never on a/b (secret) -> constant time.
    assign done    = running & (iter == K);
    assign gcd_out = a;

    always @(posedge clk) begin
        if (rst) begin
            a <= 8'd0; b <= 8'd0; iter <= 5'd0; running <= 1'b0;
        end else if (start) begin
            a <= a_in; b <= b_in; iter <= 5'd0; running <= 1'b1;
        end else if (running & (iter < K)) begin
            // one reduction step, ALWAYS executed (constant-time): the branch affects the DATA, not
            // whether we step, so `iter` (and thus `done`) is independent of the operands.
            if      (a >= b && b != 8'd0) a <= a - b;
            else if (b >  a && a != 8'd0) b <= b - a;
            iter <= iter + 5'd1;
        end
    end
endmodule
