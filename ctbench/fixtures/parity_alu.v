// parity_alu — a fault-RESISTANT 4-bit ALU (the PROVEN side of the fault-injection twin, WS-A).
//
// The datapath `r0 = op(a,b)` is computed TWICE by two structurally-distinct copies (r0 from a/b/op, r1 from
// a2/b2/op2) and compared: `error_flag = |(r0 ^ r1)` — a concurrent-error-detection (CED) duplicate-and-compare,
// the countermeasure ISO 26262 / Common Criteria (AVA_VAN fault-injection) mandate. Any single modeled fault in
// the OUT datapath makes r0 diverge from r1 while the golden copy holds, so `error_flag` rises (DETECTED) or the
// fault is logically masked (out unchanged). No modeled single stuck-at silently corrupts `out` -> PROVEN
// fault-resistant by a golden-versus-faulted 2-safety miter.
//
// WHY THE DUPLICATE PORTS a2/b2/op2 (load-bearing, do not "simplify" them away): a fault-FREE CED design has
// error_flag == 0 identically, so yosys/abc merge the two identical cones and emit error_flag as a CONSTANT 0 —
// leaving nothing to fault. Exposing the redundant datapath through distinct ports stops the merge; the proof
// harness re-ties a2:=a, b2:=b, op2:=op after extraction (`fault_check.alias_duplicate_ports`), so in operation
// the two copies see the same inputs — a genuine, un-merged duplication whose error_flag is a live function.
//
// The leaky twins: `alu_unprotected.v` hardwires error_flag=0 (a fault corrupts out undetected -> REFUSED) and
// `parity_alu_singlebit.v` checks only some output bits (a fault on an unchecked bit -> REFUSED).
module parity_alu (a, b, op, a2, b2, op2, out, error_flag);
    input  [3:0] a, b, a2, b2;
    input  [1:0] op, op2;
    output [3:0] out;
    output       error_flag;

    reg [3:0] r0, r1;
    always @* case (op)  2'b00: r0 = a  & b;  2'b01: r0 = a  | b;  2'b10: r0 = a  ^ b;  default: r0 = a  + b;  endcase
    always @* case (op2) 2'b00: r1 = a2 & b2; 2'b01: r1 = a2 | b2; 2'b10: r1 = a2 ^ b2; default: r1 = a2 + b2; endcase

    assign out        = r0;
    assign error_flag = |(r0 ^ r1);     // DETECT: the two copies disagree under a fault
endmodule
