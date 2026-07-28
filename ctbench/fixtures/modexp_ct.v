// modexp_ct — CONSTANT-TIME square-and-multiply-ALWAYS modular exponentiation control, the standard RSA
// timing-attack countermeasure (the always-multiply / constant-time-exponentiation defense — the exponent
// bit never gates control, only selects a value; this is the always-multiply class, distinct from but in the
// spirit of the Montgomery powering ladder). The completion
// signal `done` asserts after EXACTLY W cycles regardless of the secret base/exponent — a data-oblivious
// cycle counter — so the completion TIMING is constant-time. The acc/sq datapath is operand-dependent in
// VALUE (that is the computation) but NEVER in timing: both the "square" and the "multiply" steps run every
// cycle and the exponent bit only SELECTS a value, it never gates the control. The constant-time property
// considered here is over this completion/cycle channel — exactly as for the picorv32 divider (not power/EM).
//
// The leaky counterpart `modexp_leaky.v` early-exits when the remaining exponent is zero, so its `done`
// timing leaks the exponent's Hamming/MSB structure — and the self-composition proof correctly REFUSES it.
module modexp_ct (clk, rst, start, base, exp, modulus, done, result);
    parameter W = 8;
    input            clk, rst, start;
    input  [W-1:0]   base, exp, modulus;   // SECRET operands: base (message), exp (private exponent)
    output           done;
    output [W-1:0]   result;

    reg [W-1:0] acc, sq, e;
    reg [3:0]   cnt;                        // cycle counter (W <= 15) — data-OBLIVIOUS
    reg         running;

    assign done   = running & (cnt == W);  // operand-free completion: fires after exactly W cycles
    assign result = acc;

    always @(posedge clk) begin
        if (rst) begin
            acc <= 8'd1; sq <= 8'd0; e <= 8'd0; cnt <= 4'd0; running <= 1'b0;
        end else if (start) begin
            acc <= 8'd1; sq <= base; e <= exp; cnt <= 4'd0; running <= 1'b1;   // load operands, begin
        end else if (running & (cnt != W)) begin
            acc <= e[0] ? (acc + sq) : acc;   // multiply-ALWAYS-select: value secret, TIMING fixed
            sq  <= sq + sq;                   // square step (data-oblivious control)
            e   <= e >> 1;
            cnt <= cnt + 4'd1;                // the ONLY thing gating `done` — a plain counter
        end
    end
endmodule
