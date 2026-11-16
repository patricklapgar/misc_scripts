#!/usr/bin/env python3
"""
Tests for the type-string and attribute decoding in test_arm_tablegen_mig.py

Run with:
    python3 -m test_arm_tablegen_mig.py -v
  or:
    python3 test_arm_tablegen_mig.py
"""

import sys
import unittest
from arm_tablegen_mig import (
    tokenize_type_string,
    decode_token,
    type_string_to_prototype,
    decode_attrs,
)


class TestTokenizer(unittest.TestCase):
    """Verify that type strings are split into the correct token sequences."""

    def test_simple_single(self):
        self.assertEqual(tokenize_type_string("i"), ["i"])

    def test_simple_void(self):
        self.assertEqual(tokenize_type_string("v"), ["v"])

    def test_unsigned_int(self):
        self.assertEqual(tokenize_type_string("Ui"), ["Ui"])

    def test_two_ints(self):
        self.assertEqual(tokenize_type_string("ii"), ["i", "i"])

    def test_three_ints(self):
        # iii → int (int, int) — smulbb signature
        self.assertEqual(tokenize_type_string("iii"), ["i", "i", "i"])

    def test_unsigned_int_three(self):
        # UiUiUi → unsigned int (unsigned int, unsigned int)
        self.assertEqual(tokenize_type_string("UiUiUi"), ["Ui", "Ui", "Ui"])

    def test_msuint32_ptr(self):
        # UNi* → msuint32_t *
        self.assertEqual(tokenize_type_string("UNi*"), ["UNi*"])

    def test_msint32_volatile_ptr(self):
        # NiD* → msint32_t volatile *
        self.assertEqual(tokenize_type_string("NiD*"), ["NiD*"])

    def test_bitscan_forward(self):
        # _BitScanForward: UcUNi*UNi
        self.assertEqual(tokenize_type_string("UcUNi*UNi"), ["Uc", "UNi*", "UNi"])

    def test_bitscan_forward64(self):
        # _BitScanForward64: UcUNi*ULLi
        self.assertEqual(tokenize_type_string("UcUNi*ULLi"), ["Uc", "UNi*", "ULLi"])

    def test_interlocked_exchange_add(self):
        # _InterlockedExchangeAdd_acq: NiNiD*Ni
        self.assertEqual(tokenize_type_string("NiNiD*Ni"), ["Ni", "NiD*", "Ni"])

    def test_interlocked_64(self):
        # LLiLLiD*LLi
        self.assertEqual(tokenize_type_string("LLiLLiD*LLi"), ["LLi", "LLiD*", "LLi"])

    def test_void_ptr(self):
        self.assertEqual(tokenize_type_string("v*"), ["v*"])

    def test_void_const_ptr(self):
        self.assertEqual(tokenize_type_string("vC*"), ["vC*"])

    def test_const_char_ptr(self):
        # cC* → char const *
        self.assertEqual(tokenize_type_string("cC*"), ["cC*"])

    def test_varargs_sentinel(self):
        self.assertEqual(tokenize_type_string("v."), ["v", "."])

    def test_uint64(self):
        # WUi → uint64_t
        self.assertEqual(tokenize_type_string("WUi"), ["WUi"])

    def test_uint32(self):
        # ZUi → uint32_t
        self.assertEqual(tokenize_type_string("ZUi"), ["ZUi"])

    def test_ll_unsigned_int(self):
        # LLUi → unsigned long long int  (crc32d signature)
        self.assertEqual(tokenize_type_string("UiUiLLUi"), ["Ui", "Ui", "LLUi"])

    def test_uic_coprocessor(self):
        # UIiUIivC* → unsigned _Constant int, unsigned _Constant int, void const *
        self.assertEqual(
            tokenize_type_string("UIiUIivC*"),
            ["UIi", "UIi", "vC*"],
        )

    def test_long_long_mixed(self):
        # LLiiiLLi — smlald signature
        self.assertEqual(
            tokenize_type_string("LLiiiLLi"),
            ["LLi", "i", "i", "LLi"],
        )

    def test_emit_langbuiltin(self):
        # vIUiC — __emit: void (unsigned _Constant int const)
        # IUi = unsigned _Constant int, then C postfix on next token
        # Actually in .def: "vIUiC" — the C is a postfix on IUi
        self.assertEqual(tokenize_type_string("vIUiC"), ["v", "IUiC"])

    def test_ldrexd_langbuiltin(self):
        # WiWiCD* — __ldrexd: int64_t (int64_t const volatile *)
        self.assertEqual(tokenize_type_string("WiWiCD*"), ["Wi", "WiCD*"])


class TestDecodeToken(unittest.TestCase):
    """Verify individual token → C++ type translation."""

    def test_void(self):
        self.assertEqual(decode_token("v"), "void")

    def test_int(self):
        self.assertEqual(decode_token("i"), "int")

    def test_unsigned_int(self):
        self.assertEqual(decode_token("Ui"), "unsigned int")

    def test_unsigned_char(self):
        self.assertEqual(decode_token("Uc"), "unsigned char")

    def test_unsigned_short(self):
        self.assertEqual(decode_token("Us"), "unsigned short")

    def test_msuint32(self):
        self.assertEqual(decode_token("UNi"), "msuint32_t")

    def test_msint32(self):
        self.assertEqual(decode_token("Ni"), "msint32_t")

    def test_msuint32_ptr(self):
        self.assertEqual(decode_token("UNi*"), "msuint32_t *")

    def test_msint32_volatile_ptr(self):
        self.assertEqual(decode_token("NiD*"), "msint32_t volatile *")

    def test_uint64(self):
        self.assertEqual(decode_token("WUi"), "uint64_t")

    def test_uint32(self):
        self.assertEqual(decode_token("ZUi"), "uint32_t")

    def test_long_long_int(self):
        self.assertEqual(decode_token("LLi"), "long long int")

    def test_unsigned_long_long(self):
        self.assertEqual(decode_token("LLUi"), "unsigned long long int")

    def test_unsigned_long_long_alt(self):
        self.assertEqual(decode_token("ULLi"), "unsigned long long int")

    def test_void_ptr(self):
        self.assertEqual(decode_token("v*"), "void *")

    def test_void_const_ptr(self):
        self.assertEqual(decode_token("vC*"), "void const *")

    def test_char_const_ptr(self):
        self.assertEqual(decode_token("cC*"), "char const *")

    def test_int_volatile_ptr(self):
        self.assertEqual(decode_token("iD*"), "int volatile *")

    def test_ll_volatile_ptr(self):
        self.assertEqual(decode_token("LLiD*"), "long long int volatile *")

    def test_unsigned_constant_int(self):
        self.assertEqual(decode_token("UIi"), "unsigned _Constant int")

    def test_unsigned_constant_int_alt(self):
        self.assertEqual(decode_token("IUi"), "unsigned _Constant int")

    def test_int64_const(self):
        # WiC — int64_t const  (used in __ldrexd)
        self.assertEqual(decode_token("WiC"), "const int64_t")

    def test_varargs(self):
        self.assertEqual(decode_token("."), "...")

    def test_float(self):
        self.assertEqual(decode_token("f"), "float")

    def test_double(self):
        self.assertEqual(decode_token("d"), "double")

    def test_size_t(self):
        self.assertEqual(decode_token("z"), "size_t")


class TestPrototype(unittest.TestCase):
    """
    Verify full type strings → prototype strings.
    Each case maps directly to a real entry in BuiltinsARM.def.
    """

    def _check(self, type_str: str, expected: str):
        result = type_string_to_prototype(type_str)
        self.assertEqual(result, expected,
            f"\ntype_str : {type_str!r}\n"
            f"expected : {expected!r}\n"
            f"got      : {result!r}")

    # --- BUILTIN entries ---

    def test_clear_cache(self):
        # BUILTIN(__clear_cache, "vv*v*", "i")
        self._check("vv*v*", "void (void *, void *)")

    def test_smulbb(self):
        # BUILTIN(__builtin_arm_smulbb, "iii", "nc")
        self._check("iii", "int (int, int)")

    def test_qadd(self):
        self._check("iii", "int (int, int)")

    def test_qdbl(self):
        # BUILTIN(__builtin_arm_qdbl, "ii", "nc")
        self._check("ii", "int (int)")

    def test_ssat(self):
        # BUILTIN(__builtin_arm_ssat, "iiUi", "nc")
        self._check("iiUi", "int (int, unsigned int)")

    def test_usat(self):
        # BUILTIN(__builtin_arm_usat, "UiiUi", "nc")
        self._check("UiiUi", "unsigned int (int, unsigned int)")

    def test_smlald(self):
        # BUILTIN(__builtin_arm_smlald, "LLiiiLLi", "nc")
        self._check("LLiiiLLi", "long long int (int, int, long long int)")

    def test_rbit(self):
        # BUILTIN(__builtin_arm_rbit, "UiUi", "nc")
        self._check("UiUi", "unsigned int (unsigned int)")

    def test_clz(self):
        # BUILTIN(__builtin_arm_clz, "UiZUi", "nc")
        self._check("UiZUi", "unsigned int (uint32_t)")

    def test_clz64(self):
        # BUILTIN(__builtin_arm_clz64, "UiWUi", "nc")
        self._check("UiWUi", "unsigned int (uint64_t)")

    def test_ldrex_varargs(self):
        # BUILTIN(__builtin_arm_ldrex, "v.", "t")
        self._check("v.", "void (...)")

    def test_strex_varargs(self):
        # BUILTIN(__builtin_arm_strex, "i.", "t")
        self._check("i.", "int (...)")

    def test_clrex(self):
        # BUILTIN(__builtin_arm_clrex, "v", "")
        self._check("v", "void ()")

    def test_get_fpscr(self):
        # BUILTIN(__builtin_arm_get_fpscr, "Ui", "nc")
        self._check("Ui", "unsigned int ()")

    def test_set_fpscr(self):
        # BUILTIN(__builtin_arm_set_fpscr, "vUi", "nc")
        self._check("vUi", "void (unsigned int)")

    def test_vcvtr_f(self):
        # BUILTIN(__builtin_arm_vcvtr_f, "ffi", "nc")
        self._check("ffi", "float (float, int)")

    def test_vcvtr_d(self):
        # BUILTIN(__builtin_arm_vcvtr_d, "fdi", "nc")
        self._check("fdi", "float (double, int)")

    def test_ldc_coprocessor(self):
        # BUILTIN(__builtin_arm_ldc, "vUIiUIivC*", "")
        self._check("vUIiUIivC*",
                    "void (unsigned _Constant int, unsigned _Constant int, void const *)")

    def test_stc_coprocessor(self):
        # BUILTIN(__builtin_arm_stc, "vUIiUIiv*", "")
        self._check("vUIiUIiv*",
                    "void (unsigned _Constant int, unsigned _Constant int, void *)")

    def test_cdp(self):
        # BUILTIN(__builtin_arm_cdp, "vUIiUIiUIiUIiUIiUIi", "")
        self._check("vUIiUIiUIiUIiUIiUIi",
                    "void (unsigned _Constant int, unsigned _Constant int, "
                    "unsigned _Constant int, unsigned _Constant int, "
                    "unsigned _Constant int, unsigned _Constant int)")

    def test_mcr(self):
        # BUILTIN(__builtin_arm_mcr, "vUIiUIiUiUIiUIiUIi", "")
        self._check("vUIiUIiUiUIiUIiUIi",
                    "void (unsigned _Constant int, unsigned _Constant int, "
                    "unsigned int, unsigned _Constant int, "
                    "unsigned _Constant int, unsigned _Constant int)")

    def test_mrc(self):
        # BUILTIN(__builtin_arm_mrc, "UiUIiUIiUIiUIiUIi", "")
        self._check("UiUIiUIiUIiUIiUIi",
                    "unsigned int (unsigned _Constant int, unsigned _Constant int, "
                    "unsigned _Constant int, unsigned _Constant int, "
                    "unsigned _Constant int)")

    def test_mcrr(self):
        # BUILTIN(__builtin_arm_mcrr, "vUIiUIiLLUiUIi", "")
        self._check("vUIiUIiLLUiUIi",
                    "void (unsigned _Constant int, unsigned _Constant int, "
                    "unsigned long long int, unsigned _Constant int)")

    def test_mrrc(self):
        # BUILTIN(__builtin_arm_mrrc, "LLUiUIiUIiUIi", "")
        self._check("LLUiUIiUIiUIi",
                    "unsigned long long int (unsigned _Constant int, "
                    "unsigned _Constant int, unsigned _Constant int)")

    def test_cmse_TT(self):
        # BUILTIN(__builtin_arm_cmse_TT, "Uiv*", "n")
        self._check("Uiv*", "unsigned int (void *)")

    def test_dmb(self):
        # BUILTIN(__builtin_arm_dmb, "vUi", "nc")
        self._check("vUi", "void (unsigned int)")

    def test_prefetch(self):
        # BUILTIN(__builtin_arm_prefetch, "vvC*UiUi", "nc")
        self._check("vvC*UiUi", "void (void const *, unsigned int, unsigned int)")

    def test_rsr(self):
        # BUILTIN(__builtin_arm_rsr, "UicC*", "nc")
        self._check("UicC*", "unsigned int (char const *)")

    def test_rsr64(self):
        # BUILTIN(__builtin_arm_rsr64, "LLUicC*", "nc")
        self._check("LLUicC*", "unsigned long long int (char const *)")

    def test_rsrp(self):
        # BUILTIN(__builtin_arm_rsrp, "v*cC*", "nc")
        self._check("v*cC*", "void * (char const *)")

    def test_wsr(self):
        # BUILTIN(__builtin_arm_wsr, "vcC*Ui", "nc")
        self._check("vcC*Ui", "void (char const *, unsigned int)")

    def test_wsr64(self):
        # BUILTIN(__builtin_arm_wsr64, "vcC*LLUi", "nc")
        self._check("vcC*LLUi", "void (char const *, unsigned long long int)")

    def test_wsrp(self):
        # BUILTIN(__builtin_arm_wsrp, "vcC*vC*", "nc")
        self._check("vcC*vC*", "void (char const *, void const *)")

    def test_sponentry(self):
        # BUILTIN(__builtin_sponentry, "v*", "c")
        self._check("v*", "void * ()")

    # --- TARGET_BUILTIN entries (CRC32) ---

    def test_crc32b(self):
        # TARGET_BUILTIN(__builtin_arm_crc32b, "UiUiUc", "nc", "crc")
        self._check("UiUiUc", "unsigned int (unsigned int, unsigned char)")

    def test_crc32h(self):
        # TARGET_BUILTIN(__builtin_arm_crc32h, "UiUiUs", "nc", "crc")
        self._check("UiUiUs", "unsigned int (unsigned int, unsigned short)")

    def test_crc32d(self):
        # TARGET_BUILTIN(__builtin_arm_crc32d, "UiUiLLUi", "nc", "crc")
        self._check("UiUiLLUi", "unsigned int (unsigned int, unsigned long long int)")

    # --- TARGET_HEADER_BUILTIN (MSVC intrin.h) ---

    def test_bitscan_forward(self):
        # TARGET_HEADER_BUILTIN(_BitScanForward, "UcUNi*UNi", ...)
        self._check("UcUNi*UNi",
                    "unsigned char (msuint32_t *, msuint32_t)")

    def test_bitscan_forward64(self):
        # TARGET_HEADER_BUILTIN(_BitScanForward64, "UcUNi*ULLi", ...)
        self._check("UcUNi*ULLi",
                    "unsigned char (msuint32_t *, unsigned long long int)")

    def test_interlocked_and64(self):
        # TARGET_HEADER_BUILTIN(_InterlockedAnd64, "LLiLLiD*LLi", ...)
        self._check("LLiLLiD*LLi",
                    "long long int (long long int volatile *, long long int)")

    def test_interlocked_decrement64(self):
        # TARGET_HEADER_BUILTIN(_InterlockedDecrement64, "LLiLLiD*", ...)
        self._check("LLiLLiD*",
                    "long long int (long long int volatile *)")

    def test_interlocked_exchange_add_acq(self):
        # TARGET_HEADER_BUILTIN(_InterlockedExchangeAdd_acq, "NiNiD*Ni", ...)
        self._check("NiNiD*Ni",
                    "msint32_t (msint32_t volatile *, msint32_t)")

    def test_interlocked_exchange_add8(self):
        # TARGET_HEADER_BUILTIN(_InterlockedExchangeAdd8_acq, "ccD*c", ...)
        self._check("ccD*c", "char (char volatile *, char)")

    def test_interlocked_exchange_add16(self):
        # TARGET_HEADER_BUILTIN(_InterlockedExchangeAdd16_acq, "ssD*s", ...)
        self._check("ssD*s", "short (short volatile *, short)")

    def test_interlocked_compare_exchange_ptr(self):
        # TARGET_HEADER_BUILTIN(_InterlockedCompareExchangePointer_acq, "v*v*D*v*v*", ...)
        self._check("v*v*D*v*v*",
                    "void * (void * volatile *, void *, void *)")

    def test_interlocked_increment_acq(self):
        # TARGET_HEADER_BUILTIN(_InterlockedIncrement_acq, "NiNiD*", ...)
        self._check("NiNiD*", "msint32_t (msint32_t volatile *)")

    def test_interlocked_increment16(self):
        # TARGET_HEADER_BUILTIN(_InterlockedIncrement16_acq, "ssD*", ...)
        self._check("ssD*", "short (short volatile *)")

    # --- LANGBUILTIN entries ---

    def test_ldrexd_langbuiltin(self):
        # LANGBUILTIN(__ldrexd, "WiWiCD*", "", ALL_MS_LANGUAGES)
        self._check("WiWiCD*", "int64_t (int64_t const volatile *)")

    def test_move_from_coprocessor(self):
        # LANGBUILTIN(_MoveFromCoprocessor, "UiIUiIUiIUiIUiIUi", ...)
        self._check("UiIUiIUiIUiIUiIUi",
                    "unsigned int (unsigned _Constant int, unsigned _Constant int, "
                    "unsigned _Constant int, unsigned _Constant int, "
                    "unsigned _Constant int)")

    def test_move_to_coprocessor(self):
        # LANGBUILTIN(_MoveToCoprocessor, "vUiIUiIUiIUiIUiIUi", ...)
        self._check("vUiIUiIUiIUiIUiIUi",
                    "void (unsigned int, unsigned _Constant int, "
                    "unsigned _Constant int, unsigned _Constant int, "
                    "unsigned _Constant int, unsigned _Constant int)")


class TestDecodeAttrs(unittest.TestCase):
    """Verify attribute string → TableGen attribute list."""

    def test_nc(self):
        self.assertEqual(decode_attrs("nc"), ["NoThrow", "Const"])

    def test_n(self):
        self.assertEqual(decode_attrs("n"), ["NoThrow"])

    def test_nch(self):
        self.assertEqual(decode_attrs("nch"),
                         ["NoThrow", "Const", "RequireDeclaration"])

    def test_nh(self):
        self.assertEqual(decode_attrs("nh"), ["NoThrow", "RequireDeclaration"])

    def test_t(self):
        self.assertEqual(decode_attrs("t"), ["CustomTypeChecking"])

    def test_i(self):
        self.assertEqual(decode_attrs("i"), ["RuntimeLibraryFunction"])

    def test_c(self):
        self.assertEqual(decode_attrs("c"), ["Const"])

    def test_empty(self):
        self.assertEqual(decode_attrs(""), [])

    def test_h(self):
        self.assertEqual(decode_attrs("h"), ["RequireDeclaration"])

    def test_no_duplicates(self):
        # Malformed but shouldn't produce duplicates
        self.assertEqual(decode_attrs("nn"), ["NoThrow"])


if __name__ == "__main__":
    unittest.main(verbosity=2)