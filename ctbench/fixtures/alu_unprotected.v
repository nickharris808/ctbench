// alu_unprotected — the UNPROTECTED ALU: same datapath as `parity_alu.v`, but NO fault detection
// (`error_flag` hardwired 0). The teeth for WS-A: a single modeled stuck-at in the OUT datapath corrupts `out`
// with error_flag never rising, so the golden_faulted 2-safety miter finds an UNDETECTED fault (`differ` SAT)
// and the method REFUSES to certify it — "unprotected != fault-resistant".
//
// The duplicate ports a2/b2/op2 are kept ONLY so the interface matches `parity_alu.v` (the harness ties them to
// a/b/op after extraction); they drive a dead XOR so yosys keeps them and does not warn on unused inputs.
module alu_unprotected (a, b, op, a2, b2, op2, out, error_flag);
    input  [3:0] a, b, a2, b2;
    input  [1:0] op, op2;
    output [3:0] out;
    output       error_flag;

    reg [3:0] r0;
    always @* case (op) 2'b00: r0 = a & b; 2'b01: r0 = a | b; 2'b10: r0 = a ^ b; default: r0 = a + b; endcase

    assign out        = r0;
    assign error_flag = 1'b0;           // NO detection — a fault on `out` is silent

    wire _unused = ^{a2, b2, op2};      // keep the duplicate ports live (interface parity with parity_alu)
endmodule
