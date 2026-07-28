// x25519_fieldmul_leaky — the LEAKY counterpart of `x25519_fieldmul`: it early-exits once the residual
// multiplier `br` is zero, skipping the remaining doublings, so `done` timing leaks the secret multiplier's
// most-significant set-bit position (its bit-length). The completion cone therefore contains operand bits, and
// the self-composition constant-time proof correctly REFUSES to certify it (the teeth).
module x25519_fieldmul_leaky (clk, rst, start, opa, opb, modulus, done, result);
    parameter W = 16;
    input             clk, rst, start;
    input  [W-1:0]    opa, opb, modulus;   // SECRET operands
    output            done;
    output [W-1:0]    result;

    reg [W:0]   acc;
    reg [W-1:0] ar, br, mr;
    reg         running;

    assign done   = running & (br == 0);    // LEAK: completion depends on the secret multiplier's value
    assign result = acc[W-1:0];

    always @(posedge clk) begin
        if (rst) begin
            acc <= 0; ar <= 0; br <= 0; mr <= 0; running <= 1'b0;
        end else if (start) begin
            acc <= 0; ar <= opa; br <= opb; mr <= modulus; running <= 1'b1;
        end else if (running & (br != 0)) begin
            acc <= (({acc[W-1:0], 1'b0}) + (br[W-1] ? {1'b0, ar} : 0));
            br  <= br << 1;                  // early-exit when this hits 0 -> variable, secret-dependent timing
        end
    end
endmodule
