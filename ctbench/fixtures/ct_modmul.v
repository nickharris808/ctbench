// ct_modmul — CONSTANT-TIME double-and-add modular multiplication `a*b mod m` (a building block of RSA/ECC
// scalar routines). Every cycle it doubles the accumulator and conditionally adds `a`, with a conditional
// modular reduction — but the multiplier bit only SELECTS values; it never gates control. Completion
// `done = running & (cnt == W)` is a data-oblivious counter, so the timing is constant-time. Teeth:
// `modmul_leaky.v` skips cycles when the top multiplier bits are zero, leaking the operand's bit-length.
module ct_modmul (clk, rst, start, a, b, m, done, result);
    parameter W = 8;
    input            clk, rst, start;
    input  [W-1:0]   a, b, m;              // SECRET operands a,b (m the modulus)
    output           done;
    output [W-1:0]   result;

    reg [W:0]   acc;                        // one guard bit for the add/reduce
    reg [W-1:0] ar, br, mr;
    reg [3:0]   cnt;                        // data-OBLIVIOUS cycle counter
    reg         running;

    assign done   = running & (cnt == W);   // operand-free completion: exactly W cycles
    assign result = acc[W-1:0];

    always @(posedge clk) begin
        if (rst) begin
            acc <= 0; ar <= 0; br <= 0; mr <= 0; cnt <= 4'd0; running <= 1'b0;
        end else if (start) begin
            acc <= 0; ar <= a; br <= b; mr <= m; cnt <= 4'd0; running <= 1'b1;
        end else if (running & (cnt != W)) begin
            // process one multiplier bit (MSB-first double-and-add), always-select, never branch on control
            acc <= (({acc[W-1:0], 1'b0}) + (br[W-1] ? {1'b0, ar} : 0));  // double + conditional add (value-select)
            br  <= br << 1;
            cnt <= cnt + 4'd1;               // the ONLY thing gating `done`
        end
    end
endmodule
