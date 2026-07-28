// barrett_leaky — the NON-constant-time counterpart of `barrett_ct`: a naive "reduce by repeated subtraction"
// normalization that LOOPS `acc -= Q` until `acc < Q`. This is a real, tempting implementation (no multiplier,
// tiny area — a common way people "just reduce mod q") but the NUMBER of iterations, hence the completion cycle
// `done`, depends on the SECRET coefficient's magnitude, leaking it through timing. This is the Kyber/Barrett
// analog of the leaky Euclidean GCD and the leaky modexp early-exit: the self-composition constant-time proof
// MUST refuse it, because `done`'s fan-in cone now contains the secret coefficient register `acc`.
module barrett_leaky (clk, rst, start, a, done, r);
    parameter AW = 16;                      // same 16-bit interface as barrett_ct (safe-vs-leaky twin)
    parameter DW = 12;
    input                clk, rst, start;
    input  [AW-1:0]      a;                 // SECRET input to reduce mod q
    output               done;
    output [DW-1:0]      r;

    localparam [AW-1:0] Q = 16'd3329;       // Kyber prime
    reg [AW-1:0]   acc;
    reg            running;

    // LEAK: `(acc < Q)` folds the SECRET coefficient register into the completion condition -> `done` timing
    // depends on how many subtractions were needed -> NOT constant-time. (Compare barrett_ct's `cnt == W`.)
    assign done = running & (acc < Q);
    assign r    = acc[DW-1:0];

    always @(posedge clk) begin
        if (rst) begin
            acc <= 0; running <= 1'b0;
        end else if (start) begin
            acc <= a; running <= 1'b1;                       // load secret operand, begin
        end else if (running & ~(acc < Q)) begin
            acc <= acc - Q;                                  // repeated subtraction: iteration count leaks `a`
        end
    end
endmodule
