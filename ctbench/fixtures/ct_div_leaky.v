// ct_div_leaky — the LEAKY TWIN of ct_div_wide (the teeth for the constant-time scaling proof).
//
// IDENTICAL to ct_div_wide EXCEPT the completion `done_now` also fires on an EARLY-EXIT when the running
// remainder reaches zero (`rem_reg == 0`). That makes the completion cycle DATA-DEPENDENT: for operands whose
// division terminates early, `done` asserts sooner — a genuine constant-time VIOLATION (a timing side channel).
//
// Expected: the CT self-composition miter is SAT (a distinguishing operand pair exists) ⇒ this twin is REFUSED,
// AND its completion cone structurally touches the operand-derived `rem_reg` ⇒ `operand_free == False`. This is
// the non-vacuity witness: the CT check distinguishes ct_div_wide (PROVES) from ct_div_leaky (REFUSED).

module ct_div_leaky #(
	parameter WIDTH = 256
) (
	input                    clk,
	input                    resetn,
	input                    start,
	input      [WIDTH-1:0]   a,
	input      [WIDTH-1:0]   b,
	output reg               done,
	output reg [WIDTH-1:0]   q,
	output reg [WIDTH-1:0]   r
);
	localparam CW = $clog2(WIDTH) + 1;

	reg [CW-1:0]        cnt;
	reg                 running;
	reg [WIDTH-1:0]     rem_reg;
	reg [WIDTH-1:0]     a_shift;
	reg [WIDTH-1:0]     b_reg;
	reg [WIDTH-1:0]     q_reg;

	wire [WIDTH-1:0] rem_shifted = {rem_reg[WIDTH-2:0], a_shift[WIDTH-1]};
	wire             ge          = (rem_shifted >= b_reg);
	wire [WIDTH-1:0] rem_next    = ge ? (rem_shifted - b_reg) : rem_shifted;

	// LEAK: completion also fires early when the remainder is exhausted — DATA-DEPENDENT timing.
	wire done_now = running && ((cnt == WIDTH[CW-1:0]) || (rem_reg == 0 && cnt != 0));

	always @(posedge clk) begin
		if (!resetn) begin
			cnt <= 0; running <= 0; done <= 0; rem_reg <= 0; a_shift <= 0; b_reg <= 0; q_reg <= 0; q <= 0; r <= 0;
		end else begin
			done <= 0;
			if (start && !running) begin
				running <= 1; cnt <= 0; rem_reg <= 0; a_shift <= a; b_reg <= b; q_reg <= 0;
			end else if (running) begin
				if (done_now) begin
					running <= 0; done <= 1; q <= q_reg; r <= rem_reg; rem_reg <= 0; a_shift <= 0;
				end else begin
					cnt <= cnt + 1; rem_reg <= rem_next; a_shift <= {a_shift[WIDTH-2:0], 1'b0}; q_reg <= {q_reg[WIDTH-2:0], ge};
				end
			end
		end
	end
endmodule
