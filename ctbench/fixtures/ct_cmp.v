// ct_cmp — CONSTANT-TIME equality/compare that ALWAYS scans all W bits (the memcmp-hardening pattern used
// against timing side channels in MAC/tag comparison). It accumulates a difference flag every cycle but never
// exits early, so `done = running & (cnt == W)` is a data-oblivious counter — completion timing is independent
// of WHERE (or whether) the operands differ. Teeth: `cmp_leaky.v` early-exits on the first differing bit, so
// its `done` timing leaks the first-mismatch position (the classic non-constant-time memcmp).
module ct_cmp (clk, rst, start, x, y, done, equal);
    parameter W = 8;
    input          clk, rst, start;
    input  [W-1:0] x, y;                   // SECRET operands (e.g. computed tag vs expected tag)
    output         done;
    output         equal;

    reg [W-1:0] xr, yr;
    reg         diff;
    reg [3:0]   cnt;                        // data-OBLIVIOUS cycle counter
    reg         running;

    assign done  = running & (cnt == W);    // operand-free completion: always W cycles
    assign equal = ~diff;

    always @(posedge clk) begin
        if (rst) begin
            xr <= 0; yr <= 0; diff <= 1'b0; cnt <= 4'd0; running <= 1'b0;
        end else if (start) begin
            xr <= x; yr <= y; diff <= 1'b0; cnt <= 4'd0; running <= 1'b1;
        end else if (running & (cnt != W)) begin
            diff <= diff | (xr[0] ^ yr[0]);   // accumulate difference — NEVER exits early
            xr   <= xr >> 1;
            yr   <= yr >> 1;
            cnt  <= cnt + 4'd1;               // the ONLY thing gating `done`
        end
    end
endmodule
