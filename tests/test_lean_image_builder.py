from scripts.build_lean_image import is_pinned_lean_version

def test_actual_lean_release_banner():
    assert is_pinned_lean_version("Lean (version 4.19.0, x86_64-unknown-linux-gnu, commit 6caaee842e94, Release)")
    assert not is_pinned_lean_version("Lean (version 4.19.01, Release)")
    assert not is_pinned_lean_version("Lean (version 4.20.0, Release)")
