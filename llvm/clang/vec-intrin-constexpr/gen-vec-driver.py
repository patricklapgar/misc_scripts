#!/usr/bin/env python3
"""Generate per-overload test drivers for constexpr SystemZ wrappers.

Usage:
  gen-vec-driver.py HEADER [-o OUTDIR] [--skip-int128] [--skip-bool]
                           [--only NAME[,NAME...]]

HEADER must be the CONVERTED vecintrin.h (the working-tree copy that already
has __ATTRS_*_constexpr). The generated files compile against both the
before and the after header, because the wrapper names and signatures are the
same in both.

Writes into OUTDIR (default: current directory):
  gen_const.cpp    constant arguments, `const RET r = call; return r;`
  gen_runtime.cpp  same call, arguments are function parameters (control)
  gen_global.cpp   namespace-scope `RET g = call;` (static vs dynamic init)
  gen_manifest.tsv one line per generated function

Functions and globals are named <c|r|g>_<NNNN>_<wrapper>, so the report
script can group them by wrapper family.
"""
import argparse
import os
import re
import sys

ELEM = {"char": 1, "short": 2, "int": 4, "long long": 8,
        "__int128": 16, "float": 4, "double": 8}
ONES = {"char": "0xff", "short": "0xffff", "int": "0xffffffffu",
        "long long": "0xffffffffffffffffull",
        "__int128": "~(unsigned __int128)0"}

START = re.compile(r"^static inline __ATTRS_(?:o_)?ai_constexpr(?:14)?\s+(.*)$")
PP_ARCH = re.compile(r"^\s*#\s*if\s+__ARCH__\s*>=\s*(\d+)\s*$")
PP_IF = re.compile(r"^\s*#\s*(if|ifdef|ifndef)\b")
PP_ELSE = re.compile(r"^\s*#\s*(else|elif)\b")
PP_ENDIF = re.compile(r"^\s*#\s*endif\b")
RANGE = re.compile(r"__constant_range\(\s*(\w+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\)")
CONST = re.compile(r"__constant\(\s*(\w+)\s*\)")


class Unsupported(Exception):
  pass


def type_info(t):
  t = " ".join(t.split())
  if "*" in t or "&" in t:
    raise Unsupported("pointer/reference type: " + t)
  toks = t.split()
  base = " ".join(x for x in toks
                  if x not in ("__vector", "__bool", "signed", "unsigned",
                               "const"))
  if base not in ELEM:
    raise Unsupported("unknown element type: " + t)
  return {"type": t, "vec": "__vector" in toks, "bool": "__bool" in toks,
          "unsigned": "unsigned" in toks or "__bool" in toks, "base": base}


def parse_wrappers(text):
  """Return (wrappers, skipped). Tracks '#if __ARCH__ >= N' gates."""
  lines = text.split("\n")
  stack, wrappers, skipped = [], [], []
  i = 0
  while i < len(lines):
    ln = lines[i]
    m_arch = PP_ARCH.match(ln)
    if m_arch:
      stack.append(int(m_arch.group(1)))
    elif PP_IF.match(ln):
      stack.append(0)
    elif PP_ELSE.match(ln):
      if stack:
        stack[-1] = 0
    elif PP_ENDIF.match(ln):
      if stack:
        stack.pop()
    else:
      m = START.match(ln)
      if m and i + 1 < len(lines):
        j, chunk = i + 1, []
        while j < len(lines):
          chunk.append(lines[j])
          if "{" in lines[j]:
            break
          j += 1
        sig = " ".join(chunk)
        sig = sig[:sig.index("{")]
        try:
          wrappers.append(parse_sig(m.group(1), sig, max(stack or [0])))
        except Unsupported as e:
          nm = re.match(r"\s*(\w+)", sig)
          skipped.append("%s: %s" % (nm.group(1) if nm else "?", e))
        i = j
    i += 1
  return wrappers, skipped


def parse_sig(ret, sig, gate):
  nm = re.match(r"\s*(\w+)\s*\(", sig)
  if not nm:
    raise Unsupported("cannot parse signature")
  start = sig.index("(")
  depth, end = 0, -1
  for k in range(start, len(sig)):
    if sig[k] == "(":
      depth += 1
    elif sig[k] == ")":
      depth -= 1
      if depth == 0:
        end = k
        break
  if end < 0:
    raise Unsupported("unbalanced parentheses")
  params_txt, attrs = sig[start + 1:end], sig[end + 1:]

  imm = {}
  for m in CONST.finditer(attrs):
    imm[m.group(1)] = 3
  for m in RANGE.finditer(attrs):
    lo, hi = int(m.group(2)), int(m.group(3))
    imm[m.group(1)] = lo + 1 if hi > lo else lo

  params = []
  if params_txt.strip() and params_txt.strip() != "void":
    for p in params_txt.split(","):
      pm = re.match(r"^(.*?)\s*(\w+)\s*$", p.strip())
      if not pm:
        raise Unsupported("cannot parse parameter: " + p)
      params.append({"name": pm.group(2), "info": type_info(pm.group(1))})
  return {"name": nm.group(1), "ret": type_info(ret), "params": params,
          "imm": imm, "gate": gate}


def kname(info, which):
  return "K%d_%s" % (which, re.sub(r"\W+", "_", info["type"]).strip("_"))


def lane(info, i, which):
  k = (i + 3 * (which - 1)) % 7 + 1
  if info["base"] == "float":
    return "%d.5f" % k
  if info["base"] == "double":
    return "%d.5" % k
  if info["base"] == "__int128":
    return "(%s __int128)%d" % ("unsigned" if info["unsigned"] else "signed", k)
  return str(k)


def k_decl(info, which):
  base, name = info["base"], kname(info, which)
  n = 16 // ELEM[base]
  if info["bool"]:
    ones = ONES[base]
    vals = [ones if (i + which) % 2 == 0 else "0" for i in range(n)]
    return ("constexpr __vector unsigned %s %s_bits = {%s};\n"
            "constexpr %s %s = (%s)%s_bits;\n"
            % (base, name, ", ".join(vals), info["type"], name,
               info["type"], name))
  vals = [lane(info, i, which) for i in range(n)]
  return "constexpr %s %s = {%s};\n" % (info["type"], name, ", ".join(vals))


def const_arg(p, pos, imm):
  if p["name"] in imm:
    return str(imm[p["name"]])
  info = p["info"]
  if info["vec"]:
    return kname(info, 1 + pos % 2)
  if info["base"] in ("float", "double"):
    return "(%s)1.5" % info["type"]
  return "(%s)3" % info["type"]


def needed_ks(w):
  ks = []
  for pos, p in enumerate(w["params"]):
    if p["name"] not in w["imm"] and p["info"]["vec"]:
      ks.append((p["info"], 1 + pos % 2))
  return ks


def guard(gate, body):
  if gate:
    return "#if __ARCH__ >= %d\n%s#endif\n" % (gate, body)
  return body


def fn_name(kind, idx, w):
  return "%s_%04d_%s" % (kind, idx, w["name"])


def emit_const(idx, w):
  args = ", ".join(const_arg(p, k, w["imm"]) for k, p in enumerate(w["params"]))
  r = w["ret"]["type"]
  return guard(w["gate"],
               'extern "C" %s %s(void) {\n  const %s r = %s(%s);\n  return r;\n}\n'
               % (r, fn_name("c", idx, w), r, w["name"], args))


def emit_runtime(idx, w):
  decls, args = [], []
  for k, p in enumerate(w["params"]):
    if p["name"] in w["imm"]:
      args.append(str(w["imm"][p["name"]]))
    else:
      decls.append("%s a%d" % (p["info"]["type"], k))
      args.append("a%d" % k)
  r = w["ret"]["type"]
  return guard(w["gate"],
               'extern "C" %s %s(%s) {\n  const %s r = %s(%s);\n  return r;\n}\n'
               % (r, fn_name("r", idx, w), ", ".join(decls) or "void", r,
                  w["name"], ", ".join(args)))


def emit_global(idx, w):
  args = ", ".join(const_arg(p, k, w["imm"]) for k, p in enumerate(w["params"]))
  return guard(w["gate"], "%s %s = %s(%s);\n"
               % (w["ret"]["type"], fn_name("g", idx, w), w["name"], args))


def write_file(path, title, ks, bodies, wrap_extern_c=False):
  with open(path, "w") as f:
    f.write("// GENERATED by gen-vec-driver.py. Do not edit.\n// %s\n\n" % title)
    f.write("#include <vecintrin.h>\n\n")
    for (_, _), (info, which) in sorted(ks.items()):
      txt = k_decl(info, which)
      if info["base"] == "float":
        txt = "#if __ARCH__ >= 12\n%s#endif\n" % txt
      f.write(txt)
    f.write("\n")
    if wrap_extern_c:
      f.write('extern "C" {\n')
    f.write("\n".join(bodies))
    if wrap_extern_c:
      f.write('}\n')


def main():
  ap = argparse.ArgumentParser(description=__doc__,
                               formatter_class=argparse.RawTextHelpFormatter)
  ap.add_argument("header")
  ap.add_argument("-o", "--outdir", default=".")
  ap.add_argument("--skip-int128", action="store_true")
  ap.add_argument("--skip-bool", action="store_true")
  ap.add_argument("--only", default="")
  a = ap.parse_args()

  with open(a.header) as f:
    wrappers, skipped = parse_wrappers(f.read())
  only = set(x for x in a.only.split(",") if x)

  keep = []
  for w in wrappers:
    infos = [w["ret"]] + [p["info"] for p in w["params"]]
    if only and w["name"] not in only:
      continue
    if a.skip_int128 and any(i["base"] == "__int128" for i in infos):
      continue
    if a.skip_bool and any(i["bool"] for i in infos):
      continue
    keep.append(w)
  if not keep:
    sys.exit("error: no constexpr wrappers found. Did you pass the CONVERTED "
             "header (the one with __ATTRS_*_constexpr)?")

  os.makedirs(a.outdir, exist_ok=True)
  ks = {}
  for w in keep:
    for info, which in needed_ks(w):
      ks[(info["type"], which)] = (info, which)

  const_b, run_b, glob_b, manifest = [], [], [], []
  for idx, w in enumerate(keep, 1):
    const_b.append(emit_const(idx, w))
    run_b.append(emit_runtime(idx, w))
    glob_b.append(emit_global(idx, w))
    manifest.append("%04d\t%s\t%d\t%s\t%s" % (
        idx, w["name"], w["gate"], w["ret"]["type"],
        ", ".join(p["info"]["type"] for p in w["params"])))

  write_file(os.path.join(a.outdir, "gen_const.cpp"),
             "constant arguments, local const initializer", ks, const_b)
  write_file(os.path.join(a.outdir, "gen_runtime.cpp"),
             "runtime arguments (control)", ks, run_b)
  write_file(os.path.join(a.outdir, "gen_global.cpp"),
             "namespace-scope initializers", ks, glob_b, wrap_extern_c=True)
  with open(os.path.join(a.outdir, "gen_manifest.tsv"), "w") as f:
    f.write("idx\twrapper\tarch_gate\treturn\tparams\n")
    f.write("\n".join(manifest) + "\n")

  fams = sorted(set(w["name"] for w in keep))
  print("wrappers generated: %d overloads in %d families" % (len(keep), len(fams)))
  print("skipped: %d" % len(skipped))
  for s in skipped:
    print("  skipped", s)
  print("wrote gen_const.cpp gen_runtime.cpp gen_global.cpp gen_manifest.tsv in",
        a.outdir)


if __name__ == "__main__":
  main()