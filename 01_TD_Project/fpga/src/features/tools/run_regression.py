"""Build/run independent RTL-vs-NumPy regression, plus protocol assertions.

python tools/run_regression.py [--iverilog PATH] [--output DIRECTORY]
No TD project/top-level modifications. All generated vectors and logs go to --output.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import numpy as np
from feature_reference import DEFAULT_EDGES, FEATURE_NAMES, extract, process_convert

ROOT = Path(__file__).resolve().parents[1]

def write_hex(path, values, bits):
    mask = (1 << bits)-1
    path.write_text("".join(f"{int(x)&mask:0{(bits+3)//4}x}\n" for x in values), encoding="ascii")

def run(command, log):
    try:
        result = subprocess.run([str(x) for x in command], capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired as e:
        partial=(e.stdout or b'')+(e.stderr or b'')
        log.write_text((partial.decode(errors='replace') if isinstance(partial,bytes) else partial)+'\nPROCESS TIMEOUT\n',encoding='utf-8')
        raise
    log.write_text(result.stdout+result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {command[0]}\n{result.stdout}{result.stderr}")
    if "WARNING" in (result.stdout+result.stderr).upper():
        raise RuntimeError(f"Warnings must be reviewed: {log}\n{result.stdout}{result.stderr}")
    return result.stdout.strip()

def simulate(iverilog, vvp, outdir, bench, plusargs):
    exe = outdir/(bench+".vvp")
    # Keep benches out of synthesizable source glob.
    sources = sorted(ROOT.glob("*.v"))
    run([iverilog,"-g2012","-Wall","-s",bench,"-o",exe,*sources,ROOT/"sim"/(bench+".v")],
        outdir/(bench+"_compile.log"))
    result = run([vvp,exe,*[f"+{key}={path.as_posix()}" for key,path in plusargs.items()]],
                 outdir/(bench+"_run.log"))
    print(result, flush=True)

def require(condition, message):
    if not condition:
        raise AssertionError(message)

def math_tests(iverilog, vvp, outdir):
    rng = random.Random(39)
    numerators = [0,1,2**160-1,2**159,1,2**128,2**159+17]
    denominators = [0,1,1,2**159,2,2**64,2**159+18]
    radicands = [0,1,2,3,4,2**64-1,2**32]
    fixeds = [0,1,-1,65536,-65536,2**31-1,-2**31]
    while len(numerators)<40:
        numerators.append(rng.getrandbits(160));denominators.append(rng.getrandbits(rng.randrange(1,161)))
        radicands.append(rng.getrandbits(64));fixeds.append(rng.randrange(-2**31,2**31))
    paths = {"NUM":outdir/"math_n.hex","DEN":outdir/"math_d.hex","RAD":outdir/"math_r.hex", "FIX":outdir/"math_q.hex","OUT":outdir/"math.txt"}
    for key, values, bits in [("NUM",numerators,160),("DEN",denominators,160),("RAD",radicands,64),("FIX",fixeds,32)]:
        write_hex(paths[key],values,bits)
    simulate(iverilog,vvp,outdir,"tb_math",paths)
    rows = [line.split() for line in paths["OUT"].read_text().splitlines()]
    require(len(rows)==40,"Math output count")
    for i,row in enumerate(rows):
        require(int(row[0])==i,"Math order")
        require(int(row[1],16)==(numerators[i]//denominators[i] if denominators[i] else 0),f"Divider vector {i}")
        require(int(row[2])==math.isqrt(radicands[i]),f"Square root vector {i}")
        require(int(row[3])==int(denominators[i]==0),f"Divide-by-zero vector {i}")
        bits=struct.unpack("<I",struct.pack("<f",fixeds[i]/65536.))[0]
        require(int(row[4],16)==bits,f"IEEE float conversion vector {i}")
    return {"vectors":40,"divider_width":160,"sqrt_width":64,"float_rounding":"nearest-even","status":"PASS"}

def fft_tests(iverilog,vvp,outdir):
    rng=np.random.default_rng(100)
    n=np.arange(1024)
    data=np.array([
        np.rint(10000*np.sin(2*np.pi*26*n/1024)+3000*np.cos(2*np.pi*179*n/1024)),
        np.full(1024,12345),
        np.r_[32767,np.zeros(1023)],
        rng.integers(-30000,30001,1024),
        np.rint(16000*np.sin(2*np.pi*511*n/1024))*4096,
        np.where(n%2, -32768,32767)*4096,
    ],dtype=np.int64)
    paths={"INPUT":outdir/"fft_in.hex","OUT":outdir/"fft.txt"}
    write_hex(paths["INPUT"],data.ravel(),32)
    simulate(iverilog,vvp,outdir,"tb_fft1024",paths)
    rows=np.loadtxt(paths["OUT"],dtype=np.int64)
    require(rows.shape==(6*1024,4),"FFT output shape")
    errors=[]
    for c in range(6):
        block=rows[c*1024:(c+1)*1024]
        require(np.all(block[:,0]==c) and np.array_equal(block[:,1],n),f"FFT order {c}")
        actual=block[:,2]+1j*block[:,3]
        expected=np.fft.fft(data[c])/1024
        error=max(float(np.abs(actual.real-expected.real).max()),float(np.abs(actual.imag-expected.imag).max()))
        limit=8.+6e-5*np.max(np.abs(data[c]))
        require(error<=limit,f"FFT {c} max component error {error} > {limit}")
        errors.append({"case":c,"max_component_error_input_units":error,"limit":float(limit)})
    return {"transforms":6,"complex_bins_compared":6144,"errors":errors,"status":"PASS"}

def feature_tests(iverilog,vvp,outdir):
    rng=np.random.default_rng(20261005);n=np.arange(1024);t=n/4000.
    def tones(freqs,amps,offsets=None):
        offsets=offsets if offsets is not None else np.zeros(6)
        return np.array([np.rint(amp*np.sin(2*np.pi*f*t)+offset) for f,amp,offset in zip(freqs,amps,offsets)],dtype=np.int64)
    random_frame=rng.integers(-15000,15001,(6,1024))
    impulse=np.zeros((6,1024),dtype=np.int64);impulse[:,71]=16384
    high=np.tile(np.where(n%2,-32768,32767),(6,1))
    low=np.tile(n%2,(6,1))+np.array([30000,-30000,0,20000,-20000,99])[:,None]
    clamp_low=tones([100,200,700]*2,[0,0,0,4000,5000,6000])
    clamp_high=tones([100,200,700]*2,[15000,12000,10000,50,100,200])
    b_zero=tones([100,200,700]*2,[5000,3000,2000,0,0,0])
    frames=[
        tones([100,200,700]*2,[6000,4000,3000,3000,2000,1500],[1000,-500,9000,-2000,1234,-8000]),
        np.tile(np.array([12345,-9876,0,55,30000,-30000])[:,None],(1,1024)),
        impulse,high,random_frame,clamp_low,clamp_high,b_zero,
        tones(np.array([12,13,39,65,103,205])*4000/1024,[6000]*6),
        tones([100,200,700]*2,[3000]*6),
        tones([100,200,700]*2,[3000]*6),low,
    ]
    names=["multitone_100_200_700Hz_DC","constant_DC","impulse","fullscale_Nyquist",
           "seeded_broadband","ratio_lower_clamp","ratio_upper_clamp","B_zero",
           "band_boundaries","configured_edges","invalid_edges_keep_previous","one_code_AC_large_DC"]
    custom=np.array([1,4,12,26,51,101,151,251,513])
    configs=[DEFAULT_EDGES.copy() for _ in frames];configs[9]=custom.copy();configs[10]=custom.copy();configs[10][3]=configs[10][2]
    active=[DEFAULT_EDGES.copy() for _ in frames];active[9]=custom;active[10]=custom
    processes=np.array([[1.25+c*.05,35.5+c,-.125+c*.01,6000+c*10] for c in range(12)])
    process_fixed=np.floor(processes*65536).astype(np.int64);processes=process_fixed/65536.
    flags=np.zeros(12,dtype=int);flags[4]=0x0200
    paths={"RAW":outdir/"feature_raw.hex","PROCESS":outdir/"feature_process.hex","EDGES":outdir/"feature_edges.hex",
           "FLAGS":outdir/"feature_flags.hex","OUT":outdir/"features.txt"}
    write_hex(paths["RAW"],np.array(frames).ravel(),16);write_hex(paths["PROCESS"],process_fixed.ravel(),32)
    write_hex(paths["EDGES"],np.array(configs).ravel(),10);write_hex(paths["FLAGS"],flags,16)
    simulate(iverilog,vvp,outdir,"tb_feature_extract",paths)
    rows=[line.split() for line in paths["OUT"].read_text().splitlines()]
    require(len(rows)==468,"Feature output count")
    actual=np.array([int(row[2])/65536. for row in rows]).reshape(12,39)
    expected=np.array([extract(frame,process,edges) for frame,process,edges in zip(frames,processes,active)])
    # Ratio uses exported (quantized) RMS values, as required by the interface.
    for c in range(12):
        a=actual[c,0]+actual[c,1];b=actual[c,17]+actual[c,18]
        expected[c,34]=np.clip(a/b,.3,6) if b else (1. if a==0 else 6.)
    rms_idx=[0,1,2,17,18,19];pp_idx=[3,4,5,20,21,22];kurt_idx=[6,7,8,23,24,25]
    band_idx=[*range(9,17),*range(26,34)]
    errors=np.abs(actual-expected)
    limits=np.full(39,2/65536.)
    limits[band_idx]=2e-4
    require(np.all(errors<=limits),"Feature mismatch: "+str([(names[c],FEATURE_NAMES[k],actual[c,k],expected[c,k],errors[c,k]) for c,k in np.argwhere(errors>limits)[:15]]))
    expected_flags=flags.copy();expected_flags[1]|=1;expected_flags[3]|=4;expected_flags[5]|=1;expected_flags[7]|=1;expected_flags[10]|=2
    for i,row in enumerate(rows):
        c,k=divmod(i,39)
        require(int(row[0])==c and int(row[1])==k,"Output IDs")
        q=int(row[2]);float_bits=struct.unpack("<I",struct.pack("<f",q/65536.))[0]
        require(int(row[3],16)==float_bits,f"Feature fp32 {c}:{k}")
        require(int(row[4],16)==expected_flags[c],f"Quality {c}:{k}, got {row[4]}, expected {expected_flags[c]:04x}")
    for c in range(12):
        for start in [9,26]:
            total=actual[c,start:start+8].sum()
            expected_total=expected[c,start:start+8].sum()
            require((total==0 if expected_total==0 else abs(total-1.)<=8/65536.),f"Band normalization {c}:{start}")
    np.savetxt(outdir/"feature_values.csv",actual,delimiter=",",header=",".join(FEATURE_NAMES),comments="",fmt="%.9g")
    np.savetxt(outdir/"feature_expected.csv",expected,delimiter=",",header=",".join(FEATURE_NAMES),comments="",fmt="%.9g")
    np.savetxt(outdir/"example_frame.csv",frames[0].T,delimiter=",",fmt="%d")
    return {"frames":12,"features_compared":468,"cases":names,"reset_abort":"PASS",
            "input_gaps_output_backpressure":"PASS","configured_invalid_edges":"PASS",
            "max_abs_error":{"rms_g":float(errors[:,rms_idx].max()),"pp_g":float(errors[:,pp_idx].max()),
                             "kurtosis":float(errors[:,kurt_idx].max()),"band_fraction":float(errors[:,band_idx].max()),
                             "ratio":float(errors[:,34].max()),"process":float(errors[:,35:].max())},
            "last_sim_cycle":int(rows[-1][5]),"status":"PASS"}

def process_tests(iverilog,vvp,outdir):
    # Means retain fractional ADC codes, including negative current/pressure.
    data=[(16384.,16384.,400,500000,15),(18384.25,17384.5,568,500000,15),
          (14384.25,15384.5,-160,750000,15),(16384.,16384.,400,0,15),
          (18384.,17384.,400,500000,0),(16384.,16384.,400,1,15)]
    vectors=[]
    for current,pressure,temp,period,mask in data:
        vectors.extend([round(current*65536),round(pressure*65536),temp,period,mask])
    paths={"INPUT":outdir/"process_in.hex","OUT":outdir/"process.txt"}
    write_hex(paths["INPUT"],vectors,32);simulate(iverilog,vvp,outdir,"tb_process_convert",paths)
    rows=[line.split() for line in paths["OUT"].read_text().splitlines()]
    require(len(rows)==6,"Process output count")
    max_current_error=0.
    for c,(current,pressure,temp,period,mask) in enumerate(data):
        actual=np.array([int(x) for x in rows[c][1:5]])/65536.
        reference=np.array(process_convert(current,pressure,temp,period))
        flags=0
        for k in range(4):
            if not mask & (1<<k): reference[k]=0;flags|=1<<(8+k)
        if period==0 or not(mask&8): reference[3]=0;flags|=0x800
        if reference[3]>(2**31-1)/65536.: reference[3]=(2**31-1)/65536.;flags|=8
        error=np.abs(actual-reference);max_current_error=max(max_current_error,float(error[0]))
        require(np.all(error<5e-5),f"Process {c}: {actual} vs {reference}")
        require(int(rows[c][5],16)==flags,f"Process validity {c}")
    return {"snapshots":6,"zero_FG_invalid_negative_fractional_saturation":"PASS",
            "max_nominal_current_error_A":max_current_error,"status":"PASS"}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iverilog",type=Path)
    parser.add_argument("--output",type=Path,default=ROOT/"sim"/"results")
    args=parser.parse_args();outdir=args.output.resolve();outdir.mkdir(parents=True,exist_ok=True)
    iv=args.iverilog or shutil.which("iverilog")
    if iv is None:
        candidate=Path.home()/"AppData/Local/Programs/iverilog-v14/bin/iverilog.exe"
        if candidate.exists(): iv=candidate
    if iv is None: raise RuntimeError("Install Icarus Verilog or supply --iverilog")
    iv=Path(iv).resolve();vvp=iv.with_name("vvp.exe" if sys.platform=="win32" else "vvp")
    require(vvp.exists(),f"Missing {vvp}")
    report={"run_utc":datetime.now(timezone.utc).isoformat(),"scope":"Standalone feature RTL simulation, not TD implementation or physical acceptance","status":"RUNNING"}
    path=outdir/'regression_report.json'
    def save():path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        for key,check in [('math',math_tests),('fft',fft_tests),('process',process_tests),('features',feature_tests)]:
            report[key]=check(iv,vvp,outdir);save()
        report['status']='PASS';save()
    except BaseException as e:
        report.update(status='FAIL',error=type(e).__name__+': '+str(e));save();raise
    print("ALL PASS. Report: "+str(outdir/"regression_report.json"),flush=True)

if __name__=="__main__": main()
