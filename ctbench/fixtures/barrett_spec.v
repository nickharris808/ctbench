// barrett_spec — the PUBLIC golden specification for the Kyber / ML-KEM Barrett reduction (WS-B): the plain
// arithmetic contract `r == a mod 3329` over the full 16-bit coefficient domain. This is the FIPS/spec-level
// reference the `barrett_ct` datapath is bit-exact to, over ALL 2^16 inputs. Purely combinational — synthesized to the same AND/OR/XOR gate list and
// compared bit-for-bit against the combinational r-cone of `barrett_ct` (its `a_reg` flop-Q tied to `a`).
module barrett_spec (a, r);
    input  [15:0] a;
    output [11:0] r;
    assign r = a % 12'd3329;      // the modular-reduction contract, verbatim
endmodule
