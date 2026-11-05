#!/usr/bin/env python3
"""Standalone waveform RTL checks; never edits/integrates existing sources."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

EDGE = Path(__file__).resolve().parents[1]
WORKING = EDGE.parents[1]
LOCAL_BIN = WORKING.parent / "toolchain" / "bin"
CASES = [(3, 2, 0), (128, 128, 0), (512, 512, 0), (0, 1, 0), (1, 0, 0), (1, 1, 0),
         (0, 1024, 0), (1024, 0, 0), (128, 128, 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iverilog", type=Path)
    parser.add_argument("--vvp", type=Path)
    parser.add_argument("--output", type=Path, default=EDGE / "sim" / "waveform_results")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [EDGE / "rtl/edge_waveform.v", EDGE / "sim/tb_edge_waveform.v"]
    cdc = EDGE / "rtl/edge_csr_cdc.v"
    report = dict(status="RUNNING", started_utc=datetime.now(timezone.utc).isoformat(),
                  tests=[], sources=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                                     for p in [*sources, cdc]],
                  synthesis="NOT_RUN", board="NOT_RUN")

    def save():
        (out / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    compiler = args.iverilog or (LOCAL_BIN / "iverilog" if (LOCAL_BIN / "iverilog").exists()
                                 else Path(shutil.which("iverilog") or "iverilog"))
    runner = args.vvp or compiler.with_name("vvp")
    if not shutil.which(str(compiler)) or not shutil.which(str(runner)):
        report.update(status="TEST_REQUIRED", reason="iverilog/vvp unavailable; no tools installed")
        save()
        print(report["reason"])
        return 2
    env = os.environ.copy()
    lib = compiler.resolve().parent.parent / "lib"
    if sys.platform == "darwin" and lib.is_dir():
        env["DYLD_LIBRARY_PATH"] = str(lib) + (":" + env["DYLD_LIBRARY_PATH"]
                                               if env.get("DYLD_LIBRARY_PATH") else "")
    report["tools"] = dict(iverilog=str(compiler.resolve()), vvp=str(runner.resolve()))
    save()
    try:
        # Use edge_waveform itself as an independent elaboration/synthesis top.
        executable = out / "edge_waveform_elaboration.vvp"
        command = [str(compiler), "-g2012", "-Wall", "-s", "edge_waveform", "-o", str(executable), str(sources[0])]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
        (out / "elaboration.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError("Standalone top elaboration failed")
        report["tests"].append(dict(test="standalone_top_elaboration", status="PASS"))
        for pre, post, test in CASES:
            name = f"pre_{pre}_post_{post}_test_{test}"
            executable = out / (name + ".vvp")
            command = [str(compiler), "-g2012", "-Wall", "-s", "tb_edge_waveform",
                       "-P", f"tb_edge_waveform.PRE={pre}", "-P", f"tb_edge_waveform.POST={post}",
                       "-P", f"tb_edge_waveform.TEST={test}",
                       "-o", str(executable), *map(str, sources)]
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
            (out / (name + "_compile.log")).write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(name + " compile failed")
            result = subprocess.run([str(runner), str(executable)], env=env, capture_output=True,
                                    text=True, timeout=60)
            log = result.stdout + result.stderr
            (out / (name + "_run.log")).write_text(log)
            if result.returncode or "ALL PASS" not in log:
                raise RuntimeError(name + " simulation failed: " + log[-1500:])
            marker = next(line for line in log.splitlines() if "ALL PASS" in line)
            report["tests"].append(dict(test=name, status="PASS", marker=marker))
            print(marker, flush=True)
            save()
        name = "waveform_cdc_75_100MHz"
        executable = out / (name + ".vvp")
        command = [str(compiler), "-g2012", "-Wall", "-s", "tb_edge_waveform_cdc", "-o", str(executable),
                   *map(str, sources), str(cdc)]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
        (out / (name + "_compile.log")).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(name + " compile failed")
        result = subprocess.run([str(runner), str(executable)], env=env, capture_output=True, text=True, timeout=60)
        log = result.stdout + result.stderr
        (out / (name + "_run.log")).write_text(log)
        if result.returncode or "ALL PASS" not in log:
            raise RuntimeError(name + " failed: " + log[-1500:])
        marker = next(line for line in log.splitlines() if "ALL PASS" in line)
        report["tests"].append(dict(test=name, status="PASS", marker=marker))
        print(marker, flush=True)
        report["status"] = "PASS"
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        report.update(status="FAIL", reason=str(exc))
        print(report["reason"], file=sys.stderr)
    report["completed_utc"] = datetime.now(timezone.utc).isoformat()
    save()
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
