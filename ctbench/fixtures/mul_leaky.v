// mul_leaky — the LEAKY counterpart of `ct_mul`: it early-exits as soon as the residual multiplier becomes
// zero, so `done` fires after a number of cycles equal to the multiplier's MSB position — a timing channel
// that leaks the secret operand's bit-length. The completion cone contains operand bits (via `mplier==0`), so
// no operand-free inductive invariant exists and the self-composition proof correctly REFUSES to certify it.
module mul_leaky (clk, rst, start, a, b, done, prod);
    parameter W = 8;
    input            clk, rst, start;
    input  [W-1:0]   a, b;                 // SECRET operands
    output           done;
    output [2*W-1:0] prod;

    reg [2*W-1:0] acc, mcand;
    reg [W-1:0]   mplier;
    reg           running;

    assign done = running & (mplier == 0); // LEAK: completion depends on the secret multiplier's value
    assign prod = acc;

    always @(posedge clk) begin
        if (rst) begin
            acc <= 0; mcand <= 0; mplier <= 0; running <= 1'b0;
        end else if (start) begin
            acc <= 0; mcand <= {{W{1'b0}}, a}; mplier <= b; running <= 1'b1;
        end else if (running & (mplier != 0)) begin
            acc    <= mplier[0] ? (acc + mcand) : acc;
            mcand  <= mcand << 1;
            mplier <= mplier >> 1;                        // early-exit when this hits 0 -> variable timing
        end
    end
endmodule
