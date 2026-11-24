#!/usr/bin/env python3
"""Per-wrapper before/after report from measure-vec-instr.sh output.

Usage:
  report-vec-funcs.py OUTDIR NAME [NAME ...] [--opts O0,O1,O2] [--detail]
                      [--csv FILE]

OUTDIR  the -o directory given to the measurement script
NAME    source base names, e.g. gen_const gen_runtime gen_global

Reads OUTDIR/NAME-before-<opt>.s and OUTDIR/NAME-after-<opt>.s.

Functions named c_NNNN_<wrapper> / r_NNNN_<wrapper>: instruction counts per
wrapper family (all instructions, and vector instructions).
Globals named g_NNNN_<wrapper>: static (constant data) or dynamic (.bss, needs
startup code) per family, plus the number of __cxx_global_var_init functions.
"""
import argparse
import csv
import os
import re
import sys
from collections import defaultdict

INSN = re.compile(r"^\s+([a-z][a-z0-9_.]*)\b")
VEC = re.compile(r"^(v|wf|we|wc)[a-z0-9]+$")
FN = re.compile(r"^([cr])_(\d+)_(\w+)$")
GV = re.compile(r"^g_(\d+)_(\w+)$")


def parse_asm(path):
  """Return (funcs, objs, ginit): funcs[name]=[total, vec], objs[name]=section."""
  with open(path) as f:
    lines = f.read().split("\n")
  func_names = set()
  for ln in lines:
    m = re.match(r"^\s+\.type\s+([^,\s]+)\s*,\s*[@%]function", ln)
    if m:
      func_names.add(m.group(1))
  funcs, objs, ginit = {}, {}, 0
  section, cur = ".text", None
  for ln in lines:
    m = re.match(r"^\s+\.section\s+([^,\s]+)", ln)
    if m:
      section = m.group(1)
      continue
    m = re.match(r"^\s+\.(text|data|bss)\b", ln)
    if m:
      section = "." + m.group(1)
      continue
    m = re.match(r"^([A-Za-z_$][\w$.]*):", ln)
    if m:
      name = m.group(1)
      if name in func_names:
        cur = name
        funcs.setdefault(name, [0, 0])
        if re.match(r"__cxx_global_var_init(\.\d+)?$", name):
          ginit += 1
      else:
        objs[name] = section
      continue
    m = re.match(r"^\s+\.size\s+([^,\s]+)", ln)
    if m and cur == m.group(1):
      cur = None
      continue
    if cur:
      m = INSN.match(ln)
      if m:
        funcs[cur][0] += 1
        if VEC.match(m.group(1)):
          funcs[cur][1] += 1
  return funcs, objs, ginit


def report_funcs(fb, fa, detail, rows, tag):
  fam = defaultdict(lambda: dict(n=0, tb=0, ta=0, vb=0, va=0, shrank=0, grew=0))
  for fn in sorted(set(fb) | set(fa)):
    m = FN.match(fn)
    if not m:
      continue
    tb, vb = fb.get(fn, [0, 0])
    ta, va = fa.get(fn, [0, 0])
    d = fam[m.group(3)]
    d["n"] += 1
    d["tb"] += tb; d["ta"] += ta; d["vb"] += vb; d["va"] += va
    d["shrank"] += ta < tb
    d["grew"] += ta > tb
    rows.append([tag, fn, tb, ta, vb, va])
    if detail and (tb != ta or vb != va):
      print("    %-34s insn %4d -> %4d   vec %4d -> %4d" % (fn, tb, ta, vb, va))
  if not fam:
    return
  print("  %-26s %5s %9s %9s %8s %8s %7s %5s" %
        ("family", "n", "insn-bef", "insn-aft", "vec-bef", "vec-aft", "shrank", "grew"))
  tot = dict(n=0, tb=0, ta=0, vb=0, va=0, shrank=0, grew=0)
  for name in sorted(fam):
    d = fam[name]
    print("  %-26s %5d %9d %9d %8d %8d %7d %5d" %
          (name, d["n"], d["tb"], d["ta"], d["vb"], d["va"], d["shrank"], d["grew"]))
    for k in tot:
      tot[k] += d[k]
  print("  %-26s %5d %9d %9d %8d %8d %7d %5d" %
        ("TOTAL", tot["n"], tot["tb"], tot["ta"], tot["vb"], tot["va"],
         tot["shrank"], tot["grew"]))


def report_globals(ob, oa, gb, ga):
  fam = defaultdict(lambda: dict(n=0, dyn_b=0, dyn_a=0))
  for name in sorted(set(ob) | set(oa)):
    m = GV.match(name)
    if not m:
      continue
    d = fam[m.group(2)]
    d["n"] += 1
    d["dyn_b"] += ob.get(name, "").startswith(".bss")
    d["dyn_a"] += oa.get(name, "").startswith(".bss")
  if not fam:
    return
  print("  %-26s %5s %12s %12s" % ("family", "n", "dynamic-bef", "dynamic-aft"))
  tn = tb = ta = 0
  for name in sorted(fam):
    d = fam[name]
    print("  %-26s %5d %12d %12d" % (name, d["n"], d["dyn_b"], d["dyn_a"]))
    tn += d["n"]; tb += d["dyn_b"]; ta += d["dyn_a"]
  print("  %-26s %5d %12d %12d" % ("TOTAL", tn, tb, ta))
  print("  __cxx_global_var_init functions: before %d, after %d" % (gb, ga))


def main():
  ap = argparse.ArgumentParser(description=__doc__,
                               formatter_class=argparse.RawTextHelpFormatter)
  ap.add_argument("outdir")
  ap.add_argument("names", nargs="+")
  ap.add_argument("--opts", default="O0,O1,O2")
  ap.add_argument("--detail", action="store_true")
  ap.add_argument("--csv")
  a = ap.parse_args()

  rows = []
  for name in a.names:
    for opt in a.opts.split(","):
      b = os.path.join(a.outdir, "%s-before-%s.s" % (name, opt))
      f = os.path.join(a.outdir, "%s-after-%s.s" % (name, opt))
      if not (os.path.exists(b) and os.path.exists(f)):
        print("\n== %s -%s: missing .s file(s), skipped" % (name, opt))
        continue
      print("\n== %s -%s" % (name, opt))
      fb, ob, gb = parse_asm(b)
      fa, oa, ga = parse_asm(f)
      report_funcs(fb, fa, a.detail, rows, "%s-%s" % (name, opt))
      report_globals(ob, oa, gb, ga)

  if a.csv:
    with open(a.csv, "w", newline="") as fh:
      w = csv.writer(fh)
      w.writerow(["run", "function", "insn_before", "insn_after",
                  "vec_before", "vec_after"])
      w.writerows(rows)
    print("\nwrote", a.csv)


if __name__ == "__main__":
  main()