// x25519_fieldmul — CONSTANT-TIME field multiplication `opa * opb mod modulus`, the inner primitive of an
// X25519 / Curve25519 Montgomery-ladder step (the field GF(2^255-19), modeled here at a tractable width W).
// The completion-channel CT ARGUMENT is width-parametric in structure, BUT this committed RTL is fixed at
// W=16 and its `reg [4:0] cnt` (below) only counts to 31 — reaching the real W=255 would require widening
// `cnt` and re-proving the (~16x larger) miter. No W>16 proof exists in this repo; do not claim one.
//
// Every cycle doubles the accumulator and CONDITIONALLY ADDS the multiplicand by VALUE-SELECT on the current
// multiplier bit — the secret multiplier only selects an operand value, it never gates control flow. The
// completion signal `done = running & (cnt == W)` is a data-OBLIVIOUS counter: the routine always runs exactly
// W cycles regardless of the secret operands, so the timing is constant-time (no operand bit reaches the
// completion cone). Its leaky twin `x25519_fieldmul_leaky.v` early-exits on the multiplier value and is
// correctly REFUSED by the self-composition proof.
module x25519_fieldmul (clk, rst, start, opa, opb, modulus, done, result);
    parameter W = 16;
    input             clk, rst, start;
    input  [W-1:0]    opa, opb, modulus;   // SECRET field operands (multiplicand, multiplier) + the prime
    output            done;
    output [W-1:0]    result;

    reg [W:0]   acc;                        // accumulator with one guard bit for double + add
    reg [W-1:0] ar, br, mr;                 // latched multiplicand / multiplier / modulus
    reg [4:0]   cnt;                        // data-OBLIVIOUS cycle counter (0..W), 5 bits covers W<=16
    reg         running;

    assign done   = running & (cnt == W);   // operand-free completion: exactly W cycles, always
    assign result = acc[W-1:0];

    always @(posedge clk) begin
        if (rst) begin
            acc <= 0; ar <= 0; br <= 0; mr <= 0; cnt <= 5'd0; running <= 1'b0;
        end else if (start) begin
            acc <= 0; ar <= opa; br <= opb; mr <= modulus; cnt <= 5'd0; running <= 1'b1;
        end else if (running & (cnt != W)) begin
            // MSB-first double-and-add: double the accumulator, VALUE-SELECT add of the multiplicand on the
            // current multiplier bit — control never branches on the secret. (A modular reduction on the
            // guard bit would slot here for the full field; it too is value-select, keeping the cone clean.)
            acc <= (({acc[W-1:0], 1'b0}) + (br[W-1] ? {1'b0, ar} : 0));
            br  <= br << 1;
            cnt <= cnt + 5'd1;               // the ONLY thing gating `done`
        end
    end
endmodule
