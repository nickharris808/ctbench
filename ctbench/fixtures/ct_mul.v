// ct_mul — CONSTANT-TIME shift-add multiplier. Runs EXACTLY W iterations regardless of the operands:
// every cycle it conditionally adds the (shifted) multiplicand based on the current multiplier bit, but the
// bit only SELECTS a value — it never gates the control. Completion `done = running & (cnt == W)` is a plain
// data-oblivious counter, so the completion TIMING is constant-time (the product VALUE is operand-dependent,
// as it must be; only the timing channel is proven). Same completion structure as `modexp_ct` / the picorv32
// divider. Teeth: `mul_leaky.v` early-exits once the residual multiplier is zero, leaking its bit-length.
module ct_mul (clk, rst, start, a, b, done, prod);
    parameter W = 8;
    input            clk, rst, start;
    input  [W-1:0]   a, b;                 // SECRET operands
    output           done;
    output [2*W-1:0] prod;

    reg [2*W-1:0] acc, mcand;
    reg [W-1:0]   mplier;
    reg [3:0]     cnt;                     // data-OBLIVIOUS cycle counter (W <= 15)
    reg           running;

    assign done = running & (cnt == W);    // operand-free completion: fires after exactly W cycles
    assign prod = acc;

    always @(posedge clk) begin
        if (rst) begin
            acc <= 0; mcand <= 0; mplier <= 0; cnt <= 4'd0; running <= 1'b0;
        end else if (start) begin
            acc <= 0; mcand <= {{W{1'b0}}, a}; mplier <= b; cnt <= 4'd0; running <= 1'b1;
        end else if (running & (cnt != W)) begin
            acc    <= mplier[0] ? (acc + mcand) : acc;   // add-ALWAYS-select: value secret, TIMING fixed
            mcand  <= mcand << 1;
            mplier <= mplier >> 1;
            cnt    <= cnt + 4'd1;                         // the ONLY thing gating `done`
        end
    end
endmodule
