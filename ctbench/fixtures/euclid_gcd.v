// euclid_gcd — subtractive Euclidean GCD. The canonical NON-constant-time datapath: the number of
// reduction steps (hence the cycle at which `done` asserts) depends on the SECRET operands, so the
// completion time leaks operand structure. This is the negative / found-bug design: a self-composition
// proof of timing non-interference FAILS on it, and iverilog reproduces a distinguishing secret pair.
//
// Interface mirrors the self-composition transition relation for the `euclid_gcd` benchmark.
module euclid_gcd (clk, rst, start, a_in, b_in, done, gcd_out);
    input             clk, rst, start;
    input      [7:0]  a_in, b_in;      // SECRET operands (assumed non-zero)
    output            done;
    output     [7:0]  gcd_out;

    reg  [7:0] a, b;
    reg        running;

    wire eq = (a == b);
    assign done    = running & eq;      // asserts when the algorithm converges (a==b==gcd)
    assign gcd_out = a;

    always @(posedge clk) begin
        if (rst) begin
            a <= 8'd0; b <= 8'd0; running <= 1'b0;
        end else if (start) begin
            a <= a_in; b <= b_in; running <= 1'b1;   // load operands, begin
        end else if (running & ~eq) begin
            if (a > b) a <= a - b;                    // secret-dependent control -> variable latency
            else       b <= b - a;
        end
    end
endmodule
