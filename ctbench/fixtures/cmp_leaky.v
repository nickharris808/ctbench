// cmp_leaky — the LEAKY counterpart of `ct_cmp`: the classic early-exit memcmp that stops at the first
// differing bit, so `done` timing leaks the position of the first mismatch (a textbook tag/MAC timing oracle).
// Its completion cone contains operand bits, so no operand-free inductive invariant exists and the
// self-composition proof correctly REFUSES to certify constant-time.
module cmp_leaky (clk, rst, start, x, y, done, equal);
    parameter W = 8;
    input          clk, rst, start;
    input  [W-1:0] x, y;                   // SECRET operands
    output         done;
    output         equal;

    reg [W-1:0] xr, yr;
    reg         diff;
    reg         running;

    // LEAK: completion fires early once a mismatch is seen OR all bits consumed -> operand-dependent timing
    assign done  = running & (diff | (xr == 0 && yr == 0));
    assign equal = ~diff;

    always @(posedge clk) begin
        if (rst) begin
            xr <= 0; yr <= 0; diff <= 1'b0; running <= 1'b0;
        end else if (start) begin
            xr <= x; yr <= y; diff <= 1'b0; running <= 1'b1;
        end else if (running & ~diff & (xr != 0 || yr != 0)) begin
            diff <= (xr[0] ^ yr[0]);          // exits early on first mismatch -> variable timing
            xr   <= xr >> 1;
            yr   <= yr >> 1;
        end
    end
endmodule
