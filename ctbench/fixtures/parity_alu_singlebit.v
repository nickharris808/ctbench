// parity_alu_singlebit — a PARTIAL countermeasure (the second WS-A teeth): the duplicate-and-compare covers
// only output bits [2:0] and IGNORES bit 3, mirroring `pcpi_div_halfwipe.v` (a countermeasure that protects
// only part of the state). A single modeled stuck-at on the bit-3 datapath corrupts `out[3]` while `error_flag`
// — which never inspects bit 3 — stays low, so the golden_faulted miter finds an UNDETECTED fault and the
// method REFUSES it. "partial != complete": a fault-resistance proof must cover EVERY output bit.
//
// Same distinct-port trick as `parity_alu.v` (a2/b2/op2 stop abc merging the cones; the harness re-ties them).
module parity_alu_singlebit (a, b, op, a2, b2, op2, out, error_flag);
    input  [3:0] a, b, a2, b2;
    input  [1:0] op, op2;
    output [3:0] out;
    output       error_flag;

    reg [3:0] r0, r1;
    always @* case (op)  2'b00: r0 = a  & b;  2'b01: r0 = a  | b;  2'b10: r0 = a  ^ b;  default: r0 = a  + b;  endcase
    always @* case (op2) 2'b00: r1 = a2 & b2; 2'b01: r1 = a2 | b2; 2'b10: r1 = a2 ^ b2; default: r1 = a2 + b2; endcase

    assign out        = r0;
    assign error_flag = |(r0[2:0] ^ r1[2:0]);   // PARTIAL: bit 3 is NOT compared -> a bit-3 fault is silent
endmodule
