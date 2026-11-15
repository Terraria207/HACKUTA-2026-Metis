import Mathlib

-- A small compiler check, not a formalization of the acceptance paper.
def metisShortcut (n : ℕ) : ℕ :=
  if n % 2 = 0 then n / 2 else (3 * n + 1) / 2

theorem metis_example : metisShortcut 19 = 29 ∧ metisShortcut 29 = 44 := by
  norm_num [metisShortcut]

theorem metis_valuation_default : padicValNat 2 0 = 0 := by
  simp

-- Explicit hypotheses survive compiler checking.
theorem metis_conditional (n : ℕ) (h : n % 2 = 0) :
    metisShortcut n = n / 2 := by
  simp [metisShortcut, h]

#print axioms metis_example
#print axioms metis_valuation_default
#print axioms metis_conditional
