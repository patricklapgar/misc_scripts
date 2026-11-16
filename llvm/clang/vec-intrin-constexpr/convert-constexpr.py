#!/usr/bin/env python3
"""Mark the Tier 1 SystemZ vector wrappers in vecintrin.h as constexpr (C++ only).

Usage:
   convert-constexpr.py [--dry-run] [path/to/vecintrin.h]

Default path is clang/lib/Headers/vecintrin.h relative to the repository root.

What it does:
 1. Adds __ATTRS_{ai,o_ai}_constexpr and ..._constexpr14 macros after the
    existing __ATTRS_o_ai definition (skipped if already present). In C, and in
    C++ older than C++11/14, they expand to the old attributes, so C behaviour
    is unchanged.
 2. For every Tier 1 wrapper definition:
      - single-statement body  -> *_constexpr
      - multi-statement body   -> *_constexpr14 (needs C++14 relaxed constexpr)
      - body calls __builtin_s390_* -> left alone (Tier 2: needs evaluator work)

The script is idempotent: wrappers that were already converted are not matched
again. Review the resulting `git diff` before committing.
"""
import os
import re
import sys

TIER1 = set("""vec_splats vec_splat_s8 vec_splat_s16 vec_splat_s32 vec_splat_s64
vec_splat_u8 vec_splat_u16 vec_splat_u32 vec_splat_u64 vec_and vec_or vec_xor
vec_andc vec_nor vec_cmpeq vec_cmplt vec_cmple vec_cmpgt vec_cmpge vec_sel
vec_abs vec_max vec_min vec_mergeh vec_mergel vec_splat vec_extract vec_insert
vec_reve vec_float vec_signed vec_double""".split())

ANCHOR = ("#define __ATTRS_o_ai __attribute__((__overloadable__, "
         "__always_inline__))\n")

MACROS = """
#if defined(__cplusplus) && (__cplusplus >= 201103L)
#define __ATTRS_ai_constexpr __ATTRS_ai constexpr
#define __ATTRS_o_ai_constexpr __ATTRS_o_ai constexpr
#else
#define __ATTRS_ai_constexpr __ATTRS_ai
#define __ATTRS_o_ai_constexpr __ATTRS_o_ai
#endif

#if defined(__cplusplus) && (__cplusplus >= 201402L)
#define __ATTRS_ai_constexpr14 __ATTRS_ai constexpr
#define __ATTRS_o_ai_constexpr14 __ATTRS_o_ai constexpr
#else
#define __ATTRS_ai_constexpr14 __ATTRS_ai
#define __ATTRS_o_ai_constexpr14 __ATTRS_o_ai
#endif
"""


def default_path():
   root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
   return os.path.join(root, "clang", "lib", "Headers", "vecintrin.h")


def add_macros(text):
   if "__ATTRS_o_ai_constexpr " in text:
       return text, False
   if ANCHOR not in text:
       sys.exit("error: could not find the __ATTRS_o_ai definition to anchor on")
   return text.replace(ANCHOR, ANCHOR + MACROS, 1), True


def convert_wrappers(text):
   lines = text.split("\n")
   counts = {"constexpr": 0, "constexpr14": 0, "skipped_builtin": 0}

   for i in range(len(lines) - 1):
       m = re.match(r"^static inline (__ATTRS_(?:o_)?ai)\b(.*)$", lines[i])
       n = re.match(r"^(\w+)\(", lines[i + 1])
       if not (m and n and n.group(1) in TIER1):
           continue

       # Collect the function from the declarator through the matching '}'.
       j, depth, body, started = i + 1, 0, [], False
       while True:
           body.append(lines[j])
           depth += lines[j].count("{") - lines[j].count("}")
           started = started or "{" in lines[j]
           if started and depth == 0:
               break
           j += 1
       full = "\n".join(body)

       if "__builtin_s390" in full:
           counts["skipped_builtin"] += 1  # Tier 2
           continue

       # Count statements in the body only, not in __constant(...) attributes.
       inner = full[full.index("{"):]
       multi = inner.count(";") > 1
       suffix = "_constexpr14" if multi else "_constexpr"
       lines[i] = "static inline %s%s%s" % (m.group(1), suffix, m.group(2))
       counts["constexpr14" if multi else "constexpr"] += 1

   return "\n".join(lines), counts


def main():
   args = [a for a in sys.argv[1:] if a != "--dry-run"]
   dry = "--dry-run" in sys.argv[1:]
   if any(a in ("-h", "--help") for a in args):
       print(__doc__)
       return
   if len(args) > 1:
       print(__doc__)
       sys.exit(1)
   path = args[0] if args else default_path()

   with open(path) as f:
       text = f.read()

   text, added = add_macros(text)
   text, counts = convert_wrappers(text)

   print("macros added:", added)
   print("wrappers:", counts)
   if dry:
       print("dry run: %s not modified" % path)
       return
   with open(path, "w") as f:
       f.write(text)
   print("wrote", path)


if __name__ == "__main__":
   main()

