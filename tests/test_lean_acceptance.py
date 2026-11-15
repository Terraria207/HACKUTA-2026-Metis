"""Opt-in real sandbox checks. Never mock compilation and call it verification."""
import os

import pytest

from metis.config import Config
from metis.formal import verify


@pytest.mark.skipif(not os.getenv('METIS_TEST_LEAN_IMAGE') or not os.getenv('METIS_TEST_LEAN_PROJECT'),
                    reason='Real pinned Lean sandbox not configured')
def test_real_compiler_acceptance():
    config = Config(lean_image=os.environ['METIS_TEST_LEAN_IMAGE'],
                    lean_project=os.environ['METIS_TEST_LEAN_PROJECT'])
    version = 'c44e0c8ee63ca166450922a373c7409c5d26b00b'
    good = verify(config, '∀ n : ℕ, n + 0 = n', 'by intro n; simp', version, True)
    assert good['status'] == 'verified', good
    assert good['machine_verified'] is True
    assert good['image'] == config.lean_image
    assert good['mathlib_version'] == version
    assert good['toolchain'] == 'leanprover/lean4:v4.19.0'
    assert len(good['source_sha256']) == 64
    assert set(good['axioms']) <= {'propext', 'Classical.choice', 'Quot.sound'}
    bad = verify(config, '1 = (2 : ℕ)', 'by rfl', version, True)
    assert bad['status'] == 'failed', bad
    placeholder = verify(config, 'False', 'by sorry', version, True)
    assert placeholder['status'] == 'rejected', placeholder
    mismatch = verify(config, 'True', 'by trivial', 'wrong-version', True)
    assert mismatch['status'] == 'unavailable', mismatch
