"""Conservative opt-in Lean execution. Arbitrary host commands are never accepted.
Only an immutable Docker image and pinned mathlib project may execute generated code.
No image pulls, network, host secrets, privilege, or writable project mounts.
"""

import os
import re
import shutil
import subprocess
import tempfile
import hashlib
import uuid
import sys

FORBIDDEN = re.compile(
    r"\b(sorry|admit|axiom|unsafe|run_cmd|run_tac|dbg_trace|trace|logInfo|elab|macro|syntax|initialize|set_option|import|include|attribute|opaque|constant|theorem|lemma|def|namespace|section|end|example|abbrev|instance)\b|#|\bby\s+exact\s+False\.elim",
    re.I,
)
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}


def verify(config, statement, proof, mathlib_version, alignment=False):
    return _verify(config, statement, proof, mathlib_version, alignment, False)


def verify_definition(config, type_expression, value, mathlib_version, alignment=False):
    """Type-check a definition; this does not establish a theorem or novelty."""
    return _verify(config, type_expression, value, mathlib_version, alignment, True)


def _verify(config, statement, proof, mathlib_version, alignment, definition):
    base = {
        "status": "unavailable",
        "machine_verified": False,
        "statement_alignment": bool(alignment),
        "type_checked": False,
    }
    if not alignment:
        return dict(
            base,
            status="rejected",
            reason="Formal statement alignment has not passed independent review",
        )
    if (
        not re.fullmatch(r".+@sha256:[a-f0-9]{64}", config.lean_image or "")
        or not config.lean_project
        or not shutil.which("docker")
    ):
        return dict(
            base,
            reason="Requires Docker, immutable Lean image digest and pinned mathlib project",
        )
    if (
        not mathlib_version
        or not os.path.isfile(os.path.join(config.lean_project, "lean-toolchain"))
        or not os.path.isfile(os.path.join(config.lean_project, "lake-manifest.json"))
    ):
        return dict(base, reason="Pinned Lean toolchain/mathlib manifest missing")
    marker = os.path.join(config.lean_project, "METIS_MATHLIB_VERSION")
    if not os.path.isfile(marker) or open(marker, encoding="utf-8").read().strip() != mathlib_version:
        return dict(
            base, reason="Journey mathlib version does not match controlled project"
        )
    if (
        len(statement) + len(proof) > 40000
        or FORBIDDEN.search(statement + "\n" + proof)
        or any(c in statement + proof for c in ("\x00", "\r"))
    ):
        return dict(
            base, status="rejected", reason="Unsafe or placeholder Lean syntax rejected"
        )
    # Restrict generated material to one expression each. Deny new commands and comments;
    # Lean is still treated as untrusted code and runs only inside the container.
    if any(
        token in statement + proof
        for token in (
            "/-",
            "--",
            '"',
            "`",
            "\n theorem",
            "\ndef ",
            "\nlemma",
            "\nend",
            "\nnamespace",
        )
    ):
        return dict(base, status="rejected", reason="Command injection rejected")
    source = (
        "import Mathlib\n "
        + ("def" if definition else "theorem")
        + " metis_result : ("
        + statement
        + ") := "
        + proof
        + "\n#print axioms metis_result\n"
    )
    with tempfile.TemporaryDirectory(prefix="metis-lean-") as temp:
        path = os.path.join(temp, "Proof.lean")
        open(path, "w", encoding="utf-8").write(source)
        os.chmod(temp, 0o755)
        os.chmod(path, 0o644)
        container_name = "metis-proof-" + uuid.uuid4().hex
        cmd = [
            "docker",
            "run",
            "--name",
            container_name,
            "--rm",
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--memory=2g",
            "--cpus=1",
            "--user=65534:65534",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
            "-v",
            os.path.realpath(config.lean_project) + ":/project:ro",
            "-v",
            temp + ":/input:ro",
            "-w",
            "/project",
            config.lean_image,
            "lake",
            "env",
            "lean",
            "/input/Proof.lean",
        ]
        with tempfile.TemporaryFile() as log:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "metis.limited", *cmd],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=35,
                )
                log.seek(0, 2)
                size = log.tell()
                log.seek(max(0, size - 16000))
                output = log.read(16000).decode("utf-8", errors="replace")
            except (OSError, subprocess.TimeoutExpired) as exc:
                return dict(
                    base,
                    reason="Sandbox/compiler unavailable or timed out: "
                    + type(exc).__name__,
                )
            finally:
                # Killing the Docker client does not kill its container. Always remove it explicitly.
                try:
                    subprocess.run(
                        ["docker", "rm", "-f", container_name],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=10,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass
    if result.returncode in (125, 126, 127):
        return dict(base, reason="Sandbox/compiler unavailable", output=output)
    match = re.search(r"metis_result.*?depends on axioms:\s*\[([^]]*)\]", output, re.S)
    no_axioms = "metis_result" in output and "does not depend on any axioms" in output
    axioms = {s.strip() for s in match[1].split(",") if s.strip()} if match else set()
    if (
        result.returncode
        or "sorryAx" in output
        or (not match and not no_axioms)
        or axioms - ALLOWED_AXIOMS
    ):
        return dict(
            base,
            status="failed",
            reason="Compilation or axiom audit failed",
            output=output,
            axioms=sorted(axioms),
        )
    return dict(
        base,
        status="typechecked" if definition else "verified",
        machine_verified=not definition,
        type_checked=definition,
        output=output,
        axioms=sorted(axioms),
        source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        toolchain=open(os.path.join(config.lean_project, "lean-toolchain"), encoding="utf-8")
        .read()
        .strip(),
        mathlib_version=mathlib_version,
        image=config.lean_image,
    )
