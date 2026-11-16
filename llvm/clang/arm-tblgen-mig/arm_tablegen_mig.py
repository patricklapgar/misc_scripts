#!/usr/bin/env python3
"""
arm_tablegen_mig.py
Translates clang/include/clang/Basic/BuiltinsARM.def
    -> clang/include/clang/Basic/BuiltinsARM.td

Usage:
    python3 arm_tablegen_mig.py \
        --input  clang/include/clang/Basic/BuiltinsARM.def \
        --output clang/include/clang/Basic/BuiltinsARM.td
"""

import re
import argparse
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Token table — ordered longest-match first.
#
# Derived from ClangBuiltinsEmitter.cpp + every token in BuiltinsARM.def
#
# Key  : The character sequence from the .def type string
# Value: The C++ type string accepted by clang-tblgen
#
# Postfix qualifiers (* C D R) are handled separately after the base token
# is identified. The entries below cover all base tokens WITHOUT postfixes.
# ---------------------------------------------------------------------------

# Ordered from longest to shortest so greedy matching works correctly
TOKEN_TABLE: list[tuple[str, str]] = [
    ("ULLLi",  "unsigned __int128_t"),
    ("LLLi",   "__int128_t"),
    ("ULLi",   "unsigned long long int"),
    ("SLLi",   "signed long long int"),
    ("LLUi",   "unsigned long long int"),
    ("LLi",    "long long int"),
    ("UNi",    "msuint32_t"),
    ("SNi",    "signed msint32_t"),
    ("Ni",     "msint32_t"),
    ("WUi",    "uint64_t"),
    ("Wi",     "int64_t"),
    ("ZUi",    "uint32_t"),
    ("Zi",     "int32_t"),
    ("UTi",    "uint16_t"),
    ("Ti",     "int16_t"),
    ("UBi",    "uint8_t"),
    ("Bi",     "int8_t"),
    ("IUi",    "unsigned _Constant int"),
    ("UIi",    "unsigned _Constant int"),
    ("Ii",     "_Constant int"),
    ("Uc",     "unsigned char"),
    ("Ui",     "unsigned int"),
    ("Us",     "unsigned short"),
    ("Ud",     "unsigned double"),
    ("Si",     "signed int"),
    ("Sc",     "signed char"),
    ("Ss",     "signed short"),
    ("Li",     "long int"),
    ("Ld",     "long double"),
    ("v",      "void"),
    ("b",      "bool"),
    ("c",      "char"),
    ("s",      "short"),
    ("i",      "int"),
    ("f",      "float"),
    ("d",      "double"),
    ("z",      "size_t"),
    ("w",      "wchar_t"),
    ("h",      "__fp16"),
    ("x",      "_Float16"),
    ("y",      "__bf16"),
    ("a",      "__builtin_va_list"),
    ("A",      "__builtin_va_list &"),
    (".",      "..."),
]

# Postfix qualifiers that follow a base token
POSTFIX_CHARS = set("*CDR")

def tokenize_type_string(type_str: str) -> list[str]:
    """
    Split a raw .def type string into a list of individual tokens.

    Each token is a base token (from TOKEN_TABLE) optionally followed by
    postfix qualifier characters (* C D R) in any order/repetition.
    """
    tokens = []
    pos = 0
    while pos < len(type_str):
        matched = False
        for base_tok, _ in TOKEN_TABLE:
            if type_str[pos:pos + len(base_tok)] == base_tok:
                end = pos + len(base_tok)
                # Consume postfix qualifiers (* C D R digits for address space)
                while end < len(type_str) and (
                    type_str[end] in POSTFIX_CHARS or type_str[end].isdigit()
                ):
                    end += 1
                tokens.append(type_str[pos:end])
                pos = end
                matched = True
                break
        if not matched:
            # Unknown character — emit as-is and continue to avoid infinite loop
            tokens.append(type_str[pos])
            pos += 1
    return tokens

def decode_token(tok: str) -> str:
    """
    Translate a single token (base + optional postfixes) to a C++ type string
    """

    # Find the longest matching base token
    base_cpp = None
    postfix_str = tok
    for base_tok, cpp in TOKEN_TABLE:
        if tok.startswith(base_tok):
            base_cpp = cpp
            postfix_str = tok[len(base_tok):]
            break

    if base_cpp is None:
        return tok  # fallback

    if not postfix_str:
        return base_cpp

    # Decode postfix qualifiers.
    # Apply left-to-right to build up pointer/qualifier layers.
    # Ex:
    #   "vC*"  -> "void const *"
    #   "iD*"  -> "int volatile *"
    #   "v*D*" -> "void * volatile *"
    result = base_cpp
    pending_quals: list[str] = []

    for ch in postfix_str:
        if ch == '*':
            if pending_quals:
                result += " " + " ".join(pending_quals)
                pending_quals = []
            result += " *"
        elif ch == 'C':
            pending_quals.append("const")
        elif ch == 'D':
            pending_quals.append("volatile")
        elif ch == 'R':
            pending_quals.append("restrict")

    # Any remaining qualifiers after the last * apply to the base type
    if pending_quals:
        result = " ".join(pending_quals) + " " + result

    return result

def type_string_to_prototype(type_str: str) -> str:
    """
    Convert a full .def type string to a TableGen prototype string

    The first token is the return type; the rest are parameters.
    "v." -> "void (...)"
    "v"  -> "void ()"
    """
    tokens = tokenize_type_string(type_str)
    if not tokens:
        return "void ()"

    ret = decode_token(tokens[0])
    params = [decode_token(t) for t in tokens[1:]]

    if not params:
        return f"{ret} ()"
    if params == ["..."]:
        return f"{ret} (...)"
    return f"{ret} ({', '.join(params)})"

# ---------------------------------------------------------------------------
# .def -> TableGen Attribute Mapping
# ---------------------------------------------------------------------------

ATTR_MAP: dict[str, str] = {
    "n": "NoThrow",
    "c": "Const",
    "U": "Pure",
    "r": "NoReturn",
    "t": "CustomTypeChecking",
    "T": "IgnoreSignature",
    "F": "FunctionWithBuiltinPrefix",
    "f": "FunctionWithoutBuiltinPrefix",
    "h": "RequireDeclaration",
    "i": "RuntimeLibraryFunction",
    "j": "ReturnsTwice",
    "u": "UnevaluatedArguments",
    "E": "Constexpr",
    "G": "Consteval",
}

def decode_attrs(attr_str: str) -> list[str]:
    """Translate .def attr to TableGen attr"""
    attrs = []
    for ch in attr_str:
        if ch in ATTR_MAP:
            a = ATTR_MAP[ch]
            if a not in attrs:   # deduplicate
                attrs.append(a)
    return attrs

# ---------------------------------------------------------------------------
# Header constant mapping
# ---------------------------------------------------------------------------

HEADER_MAP: dict[str, str] = {
    "ARM_ACLE_H": "arm_acle.h",
    "INTRIN_H":   "intrin.h",
}

def map_header(h: str) -> str:
    return HEADER_MAP.get(h, h.lower().replace("_h", ".h"))

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class BuiltinEntry:
    macro:    str
    name:     str
    type_str: str
    attrs:    str
    lang:     Optional[str] = None
    feature:  Optional[str] = None
    header:   Optional[str] = None
    lang_hdr: Optional[str] = None

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

RE_BUILTIN = re.compile(
    r'^BUILTIN\(\s*(\w+)\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)')
RE_LANGBUILTIN = re.compile(
    r'^LANGBUILTIN\(\s*(\w+)\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*(\w+)\s*\)')
RE_TARGET_BUILTIN = re.compile(
    r'^TARGET_BUILTIN\(\s*(\w+)\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)')
RE_TARGET_HEADER_BUILTIN = re.compile(
    r'^TARGET_HEADER_BUILTIN\(\s*(\w+)\s*,\s*"([^"]*)"\s*,\s*"([^"]*)"\s*,'
    r'\s*(\w+)\s*,\s*(\w+)\s*,\s*"([^"]*)"\s*\)')

def parse_def_file(path: str) -> tuple[list[BuiltinEntry], dict[int, str]]:
    entries: list[BuiltinEntry] = []
    comment_at: dict[int, str] = {}
    pending: list[str] = []

    with open(path) as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('//'):
                pending.append(line[2:].strip())
                continue
            if pending:
                comment_at[len(entries)] = '\n'.join(pending)
                pending = []

            m = RE_TARGET_HEADER_BUILTIN.match(line)
            if m:
                feat = m.group(6).strip()
                entries.append(BuiltinEntry(
                    macro='TARGET_HEADER_BUILTIN',
                    name=m.group(1), type_str=m.group(2), attrs=m.group(3),
                    header=m.group(4), lang_hdr=m.group(5),
                    feature=feat if feat else None,
                ))
                continue
            m = RE_TARGET_BUILTIN.match(line)
            if m:
                entries.append(BuiltinEntry(
                    macro='TARGET_BUILTIN',
                    name=m.group(1), type_str=m.group(2), attrs=m.group(3),
                    feature=m.group(4),
                ))
                continue
            m = RE_LANGBUILTIN.match(line)
            if m:
                entries.append(BuiltinEntry(
                    macro='LANGBUILTIN',
                    name=m.group(1), type_str=m.group(2), attrs=m.group(3),
                    lang=m.group(4),
                ))
                continue
            m = RE_BUILTIN.match(line)
            if m:
                entries.append(BuiltinEntry(
                    macro='BUILTIN',
                    name=m.group(1), type_str=m.group(2), attrs=m.group(3),
                ))

    return entries, comment_at

# ---------------------------------------------------------------------------
# Name -> def identifier
# ---------------------------------------------------------------------------

ARM_PREFIX = "__builtin_arm_"

def name_to_def_id(name: str) -> str:
    if name.startswith(ARM_PREFIX):
        return name[len(ARM_PREFIX):]
    return name

def needs_prefix(name: str) -> bool:
    return name.startswith(ARM_PREFIX)

# ---------------------------------------------------------------------------
# TD class selection
# ---------------------------------------------------------------------------

def entry_to_td_class(entry: BuiltinEntry) -> str:
    is_prefixed = needs_prefix(entry.name)
    if entry.macro == 'BUILTIN':
        return "ARMBuiltin" if is_prefixed else "ARMNoPrefixBuiltin"
    elif entry.macro == 'LANGBUILTIN':
        # ALL_MS_LANGUAGES is the only language used in BuiltinsARM.def
        return "ARMMSLangBuiltin" if is_prefixed else "ARMNoPrefixMSLangBuiltin"
    elif entry.macro == 'TARGET_BUILTIN':
        return "ARMTargetBuiltin" if is_prefixed else "ARMNoPrefixTargetBuiltin"
    elif entry.macro == 'TARGET_HEADER_BUILTIN':
        return "ARMNoPrefixTargetLibBuiltin"
    return "ARMNoPrefixBuiltin"

# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------

def attrs_to_td(attrs: list[str]) -> str:
    return "[" + ", ".join(attrs) + "]" if attrs else "[]"

def group_key(e: BuiltinEntry) -> tuple:
    return (
        tuple(decode_attrs(e.attrs)),
        e.feature or "",
        e.header or "",
        e.lang_hdr or e.lang or "",
    )

def emit_td(entries: list[BuiltinEntry],
            comment_at: dict[int, str],
            out_path: str) -> None:

    lines: list[str] = []

    lines += [
        "//==- BuiltinsARM.td - ARM Builtin function database -------*- C++ -*-==//\n",
        "//\n",
        "// Part of the LLVM Project, under the Apache License v2.0 with LLVM Exceptions.\n",
        "// See https://llvm.org/LICENSE.txt for license information.\n",
        "// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception\n",
        "//\n",
        "//===----------------------------------------------------------------------===//\n",
        "//\n",
        "// This file defines the ARM-specific builtin function database.\n",
        "//\n",
        "//===----------------------------------------------------------------------===//\n",
        "\n",
        'include "clang/Basic/BuiltinsARMBase.td"\n',
        "\n",
    ]

    i = 0
    while i < len(entries):
        if i in comment_at:
            for cmt_line in comment_at[i].splitlines():
                lines.append(f"// {cmt_line}\n" if cmt_line else "//\n")

        # Find run of consecutive same-key entries (stop at next comment)
        key = group_key(entries[i])
        j = i + 1
        while j < len(entries) and j not in comment_at and group_key(entries[j]) == key:
            j += 1
        run = entries[i:j]

        attrs   = decode_attrs(run[0].attrs)
        feature = run[0].feature or ""
        header  = run[0].header
        lang    = run[0].lang_hdr or run[0].lang or ""

        let_parts = []
        if attrs:
            let_parts.append(f"Attributes = {attrs_to_td(attrs)}")
        if feature:
            let_parts.append(f'Features = "{feature}"')
        if header:
            let_parts.append(f'Header = "{map_header(header)}"')
        if lang and lang != "ALL_LANGUAGES":
            let_parts.append(f'Languages = "{lang}"')
        elif lang == "ALL_LANGUAGES":
            let_parts.append('Languages = "ALL_LANGUAGES"')

        use_block = bool(let_parts)
        if use_block:
            lines.append("let " + ", ".join(let_parts) + " in {\n")
            indent = "\t"
        else:
            indent = ""

        for e in run:
            def_id   = name_to_def_id(e.name)
            td_class = entry_to_td_class(e)
            proto    = type_string_to_prototype(e.type_str)
            lines.append(f'{indent}def {def_id} : {td_class}<"{proto}">;\n')

        if use_block:
            lines.append("}\n")
        lines.append("\n")
        i = j

    with open(out_path, 'w') as f:
        f.writelines(lines)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert BuiltinsARM.def to BuiltinsARM.td")
    parser.add_argument("--input",  default="clang/include/clang/Basic/BuiltinsARM.def")
    parser.add_argument("--output", default="clang/include/clang/Basic/BuiltinsARM.td")
    args = parser.parse_args()

    entries, comment_at = parse_def_file(args.input)
    emit_td(entries, comment_at, args.output)
    print(f"Wrote {len(entries)} builtins to {args.output}")


if __name__ == "__main__":
    main()