#!/usr/bin/env bash
# Compare SystemZ vector-instruction counts with and without the modified
# header file
#
#   BEFORE header = vecintrin.h as committed in git HEAD
#   AFTER  header = vecintrin.h in your working tree
#
# Usage:
#   Single files:  measure-vec-instr.sh [options] file.cpp [file2.cpp ...]
#   CMake project: measure-vec-instr.sh [options] -p PROJECT_DIR
#
# Options:
#   -x CXX     clang++ that can target s390x (env CXX; default: autodetect)
#   -C CC      matching clang (default: CXX without the "++")
#   -r PARENT  directory that contains llvm-project (default: derived from the
#              script's own location)
#   -I DIR     extra include dir, repeatable (single-file mode)
#   -O "O0 O2" optimisation levels (default "O0 O2"; "O2" in project mode)
#   -o DIR     output directory (default /tmp/vec-measure)
#   -s SYSROOT s390x sysroot (ignored on a native s390x machine)
#   -f "FLAGS" extra compiler flags, e.g. "-DNDEBUG"
#   -p DIR     project mode: configure+build this CMake project twice
#   -n NAME    label for output files (project mode; default: dir name)
#   -t "T1 T2" CMake targets to build (project mode; default: all)
#   -c "ARGS"  extra -D options for cmake configure (project mode)
#   -g DIR     where to count Tier 1 call sites in source (default: -p dir)

set -euo pipefail
export LC_ALL=C

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HDR="$(dirname "$SCRIPT_DIR")"             # llvm-project root
HDR_REL="clang/lib/Headers/vecintrin.h"    # must stay repo-relative for git show

CXX="${CXX:-}"; CC=""
OPTS=""; OUT="/tmp/vec-measure"
SYSROOT=""; EXTRA_FLAGS=""
PROJECT=""; NAME=""; TARGETS=""; CMAKE_ARGS=""; GREP_PATH=""
INCLUDES=()

while getopts "x:C:I:O:o:s:f:p:n:t:c:g:r:h" opt; do
  case "$opt" in
    x) CXX="$OPTARG" ;;
    C) CC="$OPTARG" ;;
    I) INCLUDES+=("-I$OPTARG") ;;
    O) OPTS="$OPTARG" ;;
    o) OUT="$OPTARG" ;;
    s) SYSROOT="$OPTARG" ;;
    f) EXTRA_FLAGS="$OPTARG" ;;
    p) PROJECT="$OPTARG" ;;
    n) NAME="$OPTARG" ;;
    t) TARGETS="$OPTARG" ;;
    c) CMAKE_ARGS="$OPTARG" ;;
    g) GREP_PATH="$OPTARG" ;;
    r) HDR="$OPTARG/llvm-project" ;;
    h|*) sed -n '2,/^$/p' "${BASH_SOURCE[0]}"; exit 1 ;;
  esac
done
shift $((OPTIND - 1))

if [ -z "$OPTS" ]; then
  if [ -n "$PROJECT" ]; then OPTS="O2"; else OPTS="O0 O2"; fi
fi
if [ -z "$PROJECT" ] && [ "$#" -lt 1 ]; then
  echo "error: give source files or -p DIR (-h for help)" >&2; exit 1
fi
[ -f "$HDR/$HDR_REL" ] || { echo "error: $HDR/$HDR_REL not found (use -r)" >&2; exit 1; }

if [ -z "$CXX" ]; then
  for c in "$HDR/build/bin/clang++" "$HDR/../build/bin/clang++" \
           /opt/homebrew/opt/llvm/bin/clang++; do
    if [ -x "$c" ]; then CXX="$c"; break; fi
  done
fi
[ -n "$CXX" ] || { echo "error: no clang++ found; pass -x" >&2; exit 1; }
[ -n "$CC" ] || CC="${CXX%++}"

targets="$("$CXX" -print-targets 2>/dev/null || true)"
if ! grep -qi systemz <<<"$targets"; then
  echo "error: $CXX was not built with the SystemZ target" >&2; exit 1
fi

# --- header snapshots -------------------------------------------------------
BEFORE_DIR="$OUT/hdr-before"
AFTER_DIR="$OUT/hdr-after"
mkdir -p "$BEFORE_DIR" "$AFTER_DIR"
git -C "$HDR" show "HEAD:$HDR_REL" > "$BEFORE_DIR/vecintrin.h"
cp "$HDR/$HDR_REL" "$AFTER_DIR/vecintrin.h"

if cmp -s "$BEFORE_DIR/vecintrin.h" "$AFTER_DIR/vecintrin.h"; then
  echo "warning: working-tree vecintrin.h is identical to HEAD; nothing to compare" >&2
fi

# --- helpers ------------------------------------------------------------------
# Vector facility mnemonics: v*, plus wf*/we*/wc* (scalar FP in a vector reg).
count_vec() {
  { grep -E '^[[:space:]]+(v|wf|we|wc)[a-z0-9]+' "$1" || true; } | wc -l | tr -d ' '
}
histogram() {
  { grep -E '^[[:space:]]+(v|wf|we|wc)[a-z0-9]+' "$1" || true; } \
    | awk '{print $1}' | sort | uniq -c | sort -rn
}
count_ginit() {  # global-initializer functions emitted by the front end
  grep -c '_GLOBAL__sub_I_' "$1" || true
}

TIER1_RE='vec_(splats|splat_[su](8|16|32|64)|splat|and|or|xor|andc|nor|cmp(eq|lt|le|gt|ge)|sel|abs|max|min|mergeh|mergel|extract|insert|reve|float|signed|double)'

# Static count of Tier 1 call sites in the project source.
# TODO: for C support add --include='*.c' and --include='*.cc'.
call_sites() {
  grep -rhoE --include='*.cpp' --include='*.h' --include='*.hpp' \
       --exclude-dir=.git --exclude-dir='build*' \
       "(^|[^A-Za-z0-9_])${TIER1_RE}\(" "${GREP_PATH:-$PROJECT}" 2>/dev/null \
    | sed -E 's/^[^v]*(vec_[a-z0-9_]+)\($/\1/' | sort | uniq -c | sort -rn || true
}

build_variant() {   # build_variant <before|after> <hdr_dir> <opt>
  local v="$1" hdr="$2" o="$3" bdir="$OUT/$NAME-$1-$3"
  local flags="-march=z15 -mzvector -save-temps=obj -Wno-c++11-narrowing -$o -I$hdr $EXTRA_FLAGS"
  local cross=() tgt=()
  if [ "$(uname -m)" != s390x ]; then
    flags="--target=s390x-linux-gnu $flags"
    cross=(-DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=s390x
           -DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY)
    if [ -n "$SYSROOT" ]; then cross+=(-DCMAKE_SYSROOT="$SYSROOT"); fi
  fi
  rm -rf "$bdir"; mkdir -p "$OUT"
  # shellcheck disable=SC2086
  cmake -S "$PROJECT" -B "$bdir" -G Ninja -DCMAKE_BUILD_TYPE=None \
    -DCMAKE_C_COMPILER="$CC" -DCMAKE_CXX_COMPILER="$CXX" \
    -DCMAKE_C_FLAGS="$flags" -DCMAKE_CXX_FLAGS="$flags" \
    ${cross[@]+"${cross[@]}"} $CMAKE_ARGS > "$bdir.configure.log" 2>&1 \
    || { echo "error: configure failed, see $bdir.configure.log" >&2; return 1; }
  # shellcheck disable=SC2206
  if [ -n "$TARGETS" ]; then tgt=(--target $TARGETS); fi
  # -k 0: keep going past failures so one broken file doesn't hide the rest.
  cmake --build "$bdir" ${tgt[@]+"${tgt[@]}"} -- -k 0 > "$bdir.build.log" 2>&1 \
    || echo "warning: $v/-$o build had failures (see $bdir.build.log); counting what was produced" >&2
}

per_file_counts() {  # path<TAB>count for every .s file under <bdir>
  find "$1" -name '*.s' -not -path '*/CMakeFiles/[0-9]*' -not -path '*/CMakeScratch/*' -print0 \
    | while IFS= read -r -d '' f; do
        printf '%s\t%s\n' "${f#"$1"/}" "$(count_vec "$f")"
      done | sort
}

all_histogram() {
  find "$1" -name '*.s' -not -path '*/CMakeFiles/[0-9]*' -not -path '*/CMakeScratch/*' \
    -exec cat {} + | { grep -E '^[[:space:]]+(v|wf|we|wc)[a-z0-9]+' || true; } \
    | awk '{print $1}' | sort | uniq -c | sort -rn
}

compare_project() {  # compare_project <opt>
  local b="$OUT/$NAME-before-$1" a="$OUT/$NAME-after-$1" t="$OUT/$NAME-$1-perfile.tsv"
  join -t $'\t' -a1 -a2 -e 0 -o 0,1.2,2.2 \
    <(per_file_counts "$b") <(per_file_counts "$a") > "$t"
  echo "-- vector instructions at -$1 (C vs C++ is guessed from the file name)"
  awk -F'\t' '
    { k = ($1 ~ /\.(cpp|cc|cxx)(\.|$)/) ? "C++" : "C/other"
      b[k]+=$2; a[k]+=$3; B+=$2; A+=$3; if ($2!=$3) n++ }
    END { printf "%-9s %10s %10s %8s\n","","before","after","delta"
          for (k in b) printf "%-9s %10d %10d %+8d\n",k,b[k],a[k],a[k]-b[k]
          printf "%-9s %10d %10d %+8d\n","total",B,A,A-B
          printf "files whose count changed: %d\n", n+0 }' "$t"
  echo "-- files that changed (largest decrease first)"
  awk -F'\t' '$2!=$3 {printf "%+6d  %6d -> %-6d  %s\n",$3-$2,$2,$3,$1}' "$t" | sort -n | head -20 || true
  diff <(all_histogram "$b") <(all_histogram "$a") > "$OUT/$NAME-diff-$1.txt" || true
  echo "per-file table: $t   mnemonic diff: $OUT/$NAME-diff-$1.txt"
}

compile() {  # compile <hdr_dir> <src> <opt> <out.s>
  local sys=()
  if [ -n "$SYSROOT" ]; then sys=(--sysroot="$SYSROOT"); fi
  # shellcheck disable=SC2086
  "$CXX" --target=s390x-linux-gnu -march=z15 -mzvector -std=c++17 -S \
    -Wno-c++11-narrowing ${sys[@]+"${sys[@]}"} $EXTRA_FLAGS \
    -"$3" -I"$1" ${INCLUDES[@]+"${INCLUDES[@]}"} "$2" -o "$4"
}

# --- project mode ---------------------------------------------------------------
mkdir -p "$OUT"
status=0

if [ -n "$PROJECT" ]; then
  NAME="${NAME:-$(basename "$PROJECT")}"
  printf '\n== %s: Tier 1 call sites in source (static count)\n' "$NAME"
  call_sites
  for o in $OPTS; do
    printf '\n== %s at -%s\n' "$NAME" "$o"
    build_variant before "$BEFORE_DIR" "$o" || exit 1
    build_variant after  "$AFTER_DIR"  "$o" || exit 1
    compare_project "$o"
  done
  exit 0
fi

# --- single-file mode -----------------------------------------------------------
for src in "$@"; do
  name="$(basename "${src%.*}")"
  printf '\n== %s\n' "$src"
  printf '%-5s %-14s %-14s %-9s %-14s %-14s\n' \
    opt "vec-insn-before" "vec-insn-after" delta "ginit-before" "ginit-after"
  for o in $OPTS; do
    b="$OUT/$name-before-$o.s"; a="$OUT/$name-after-$o.s"
    if ! compile "$BEFORE_DIR" "$src" "$o" "$b" 2>"$OUT/$name-before-$o.err"; then
      echo "$o: BEFORE compile failed, see $OUT/$name-before-$o.err" >&2; status=1; continue
    fi
    if ! compile "$AFTER_DIR" "$src" "$o" "$a" 2>"$OUT/$name-after-$o.err"; then
      echo "$o: AFTER compile failed, see $OUT/$name-after-$o.err" >&2; status=1; continue
    fi
    vb=$(count_vec "$b"); va=$(count_vec "$a")
    printf '%-5s %-14s %-14s %-9s %-14s %-14s\n' \
      "$o" "$vb" "$va" "$((va - vb))" "$(count_ginit "$b")" "$(count_ginit "$a")"
    diff <(histogram "$b") <(histogram "$a") > "$OUT/$name-diff-$o.txt" || true
  done
done

printf '\nAssembly, stderr and per-mnemonic diffs are in %s\n' "$OUT"
exit "$status"
