// modexp_leaky — the NON-constant-time counterpart of `modexp_ct`: a square-and-multiply modular
// exponentiation that EARLY-EXITS when the remaining exponent register is all zeros. That is a real,
// tempting optimization (skip the trailing zero exponent bits), but it makes the completion cycle — hence
// `done` — depend on the SECRET exponent's structure, leaking it through timing. This is the modexp analog
// of the leaky Euclidean GCD: the self-composition constant-time proof MUST refuse it, because the
// completion signal's fan-in cone now contains the secret exponent register.
module modexp_leaky (clk, rst, start, base, exp, modulus, done, result);
    parameter W = 8;
    input            clk, rst, start;
    input  [W-1:0]   base, exp, modulus;   // SECRET operands
    output           done;
    output [W-1:0]   result;

    reg [W-1:0] acc, sq, e;
    reg [3:0]   cnt;
    reg         running;

    // LEAK: `(e == 0)` folds the SECRET exponent register into the completion condition -> `done` timing
    // depends on the exponent -> NOT constant-time. (Compare modexp_ct's operand-free `cnt == W`.)
    assign done   = running & ((cnt == W) | (e == 8'd0));
    assign result = acc;

    always @(posedge clk) begin
        if (rst) begin
            acc <= 8'd1; sq <= 8'd0; e <= 8'd0; cnt <= 4'd0; running <= 1'b0;
        end else if (start) begin
            acc <= 8'd1; sq <= base; e <= exp; cnt <= 4'd0; running <= 1'b1;
        end else if (running & ~((cnt == W) | (e == 8'd0))) begin
            acc <= e[0] ? (acc + sq) : acc;
            sq  <= sq + sq;
            e   <= e >> 1;
            cnt <= cnt + 4'd1;
        end
    end
endmodule
