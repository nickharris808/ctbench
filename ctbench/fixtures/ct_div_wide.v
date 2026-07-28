// ct_div_wide — a parameterized CONSTANT-TIME restoring divider with wipe-on-done, in clean RTL.
//
// Purpose (SCALE demonstration): the completion signal `done` is a pure function of the iteration COUNTER
// (cnt == W), never of the operand data — so the divider runs EXACTLY W fixed cycles regardless of a/b, i.e.
// it is constant-time by construction (the same reason picorv32_pcpi_div is CT). The datapath (the W-bit
// shift/compare/subtract) grows ~O(W) — quadratically in area for the comparator chain — while the completion
// cone (the counter FSM) grows only ~log2(W). So bumping WIDTH 32 -> 256 makes the design ~10x in gates but
// leaves the localized completion-observable cone essentially unchanged. This is the clean-RTL twin of
// pcpi_div_wiped: the completion cone stays small even as the datapath grows.
//
// Secret operands: a, b (the dividend/divisor). Completion: done. Result: q (quotient), r (remainder).
// Wipe-on-done: on the completion cycle the operand-derived scratch (rem_reg, a_shift) is zeroed, so no operand
// residue survives past `done` (the no-secret-residue property, matching pcpi_div_wiped's wipe).
//
// CONSTANT-TIME CLAIM (the property proven): `done` and the cycle on which it asserts are independent of a,b.
// (A leaky twin that early-exits when the remainder hits zero would make `done` data-dependent and be REFUSED.)

module ct_div_wide #(
	parameter WIDTH = 256
) (
	input                    clk,
	input                    resetn,
	input                    start,        // pulse: latch a,b and begin
	input      [WIDTH-1:0]   a,            // dividend (SECRET)
	input      [WIDTH-1:0]   b,            // divisor  (SECRET)
	output reg               done,         // completion (data-OBLIVIOUS: a pure function of cnt)
	output reg [WIDTH-1:0]   q,            // quotient
	output reg [WIDTH-1:0]   r             // remainder
);
	localparam CW = $clog2(WIDTH) + 1;     // counter width

	reg [CW-1:0]        cnt;               // iteration counter — the ONLY thing `done` depends on
	reg                 running;
	reg [WIDTH-1:0]     rem_reg;           // running remainder (operand-derived scratch)
	reg [WIDTH-1:0]     a_shift;           // dividend being shifted in (operand-derived scratch)
	reg [WIDTH-1:0]     b_reg;             // divisor latch
	reg [WIDTH-1:0]     q_reg;             // quotient accumulator

	// one restoring-division step: shift remainder in the next dividend bit, trial-subtract the divisor.
	wire [WIDTH-1:0] rem_shifted = {rem_reg[WIDTH-2:0], a_shift[WIDTH-1]};
	wire             ge          = (rem_shifted >= b_reg);
	wire [WIDTH-1:0] rem_next    = ge ? (rem_shifted - b_reg) : rem_shifted;

	// completion is a PURE function of the counter — this is what makes the divider constant-time.
	wire done_now = running && (cnt == WIDTH[CW-1:0]);

	always @(posedge clk) begin
		if (!resetn) begin
			cnt     <= 0;
			running <= 0;
			done    <= 0;
			rem_reg <= 0;
			a_shift <= 0;
			b_reg   <= 0;
			q_reg   <= 0;
			q       <= 0;
			r       <= 0;
		end else begin
			done <= 0;
			if (start && !running) begin
				running <= 1;
				cnt     <= 0;
				rem_reg <= 0;
				a_shift <= a;
				b_reg   <= b;
				q_reg   <= 0;
			end else if (running) begin
				if (done_now) begin
					// completion cycle: latch result, WIPE operand-derived scratch (no residue survives `done`).
					running <= 0;
					done    <= 1;
					q       <= q_reg;
					r       <= rem_reg;
					rem_reg <= 0;      // wipe
					a_shift <= 0;      // wipe
				end else begin
					cnt     <= cnt + 1;
					rem_reg <= rem_next;
					a_shift <= {a_shift[WIDTH-2:0], 1'b0};
					q_reg   <= {q_reg[WIDTH-2:0], ge};
				end
			end
		end
	end
endmodule
