// barrett_buggy — a BUGGY Barrett reduction (the WS-B teeth): identical to `barrett_ct.v` except the Barrett
// SHIFT is WRONG (K = 25 instead of the canonical 26). The reciprocal constant V = round(2^26/3329) is
// calibrated for a 2^26 shift; using 2^25 scales the quotient estimate `t` by ~2x, an error far outside what
// the single +q/-q correction can absorb, so `r != a mod 3329` on the majority of coefficients (62206 / 65536).
// The equivalence miter against `barrett_spec` is then SATISFIABLE — a refutation over the input domain exists —
// and the method REFUSES to certify it. A timing check correctly does NOT flag it, which is what makes
// this fixture an out-of-remit control.
//
// (A subtler off-by-one in V — e.g. 20158 or even 20000 — is NOT used here: Barrett's ±q correction absorbs
// small reciprocal errors, so those variants are STILL bit-exact over the 16-bit domain and would be a
// strawman "bug" that actually passes. K=25 is a genuine, unabsorbable miscalibration. The completion channel
// is unchanged, so this twin is still CONSTANT-TIME — the bug is purely in the VALUE, isolating the
// functional-correctness proof from the timing proof: CT alone would accept this buggy core.)
module barrett_buggy (clk, rst, start, a, done, r);
    parameter  AW = 16;
    parameter  DW = 12;
    parameter  W  = 8;
    localparam integer   V = 20159;         // canonical reciprocal — calibrated for a 2^26 shift
    localparam integer   K = 25;            // BUG: should be 26; the shift no longer matches V -> t is ~2x off
    localparam [16:0]    Q = 17'd3329;

    input                clk, rst, start;
    input  [AW-1:0]      a;
    output               done;
    output [DW-1:0]      r;

    reg [AW-1:0] a_reg;
    reg [3:0]    cnt;
    reg          running;

    assign done = running & (cnt == W);

    wire [30:0]        prod = V * a_reg;
    wire [12:0]        t    = (prod + (1 << (K-1))) >> K;
    wire [16:0]        tq   = t * Q;
    wire signed [17:0] sub  = $signed({2'b00, a_reg}) - $signed({1'b0, tq});
    wire signed [17:0] cadd = sub[17]              ? (sub  + $signed({1'b0, Q})) : sub;
    wire signed [17:0] csub = (cadd >= $signed({1'b0, Q})) ? (cadd - $signed({1'b0, Q})) : cadd;
    assign r = csub[DW-1:0];

    always @(posedge clk) begin
        if (rst) begin
            a_reg <= 0; cnt <= 4'd0; running <= 1'b0;
        end else if (start) begin
            a_reg <= a; cnt <= 4'd0; running <= 1'b1;
        end else if (running & (cnt != W)) begin
            cnt <= cnt + 4'd1;
        end
    end
endmodule
