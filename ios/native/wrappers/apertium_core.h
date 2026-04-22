// apertium-ios-native/wrappers/apertium_core.h
//
// Public C API over the library-ified Apertium tools. Swift imports this
// header through a bridging header in the iOS app target.
//
// Each wrapper takes a string input, returns a string output (via the
// ApertiumResult struct). A dedicated `tmp_dir` parameter is required
// because Apertium's tools hold onto FILE* streams and the simplest way
// to feed them from an in-memory string is via a caller-owned tmpfile —
// iOS apps must use NSTemporaryDirectory(); macOS host tests can use
// "/tmp".
//
// Return-value ownership:
//   On success, .output is a heap-allocated UTF-8 string and .error is
//   NULL. On failure, .output is NULL and .error is a heap-allocated
//   diagnostic string. In either case the caller must pass the result
//   back to apertium_result_free() exactly once.

#ifndef APERTIUM_CORE_H
#define APERTIUM_CORE_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ApertiumResult {
  char* output;  // heap-allocated; NULL on failure
  char* error;   // heap-allocated; NULL on success
} ApertiumResult;

void apertium_result_free(ApertiumResult r);

// --- lttoolbox -------------------------------------------------------------

// lt-proc. `flag` is a single-letter mode selector matching the CLI:
//   "a" analysis, "g" generation, "b" bilingual, "p" post-gen,
//   "s" SAO, "t" transliteration, "e" decompose-nouns.
ApertiumResult apertium_lt_proc(const char* input,
                                const char* bin_path,
                                const char* flag,
                                const char* tmp_dir);

// --- apertium --------------------------------------------------------------

// apertium-pretransfer. Flags: "z" (null-flush), "n" (no-surface-forms),
// "e" (compounds).
ApertiumResult apertium_pretransfer(const char* input,
                                    const char* flags,
                                    const char* tmp_dir);

// apertium-posttransfer. Flags: "z" (null-flush).
ApertiumResult apertium_posttransfer(const char* input,
                                     const char* flags,
                                     const char* tmp_dir);

// apertium-transfer. `trules_file` = .tNx source XML, `datafile` =
// compiled .tNx.bin, `biltrans_file` may be NULL / "" (required only
// when the `-b` flag isn't set). Flags: b n c w t T z.
ApertiumResult apertium_transfer(const char* input,
                                 const char* trules_file,
                                 const char* datafile,
                                 const char* biltrans_file,
                                 const char* flags,
                                 const char* tmp_dir);

// apertium-interchunk. Flags: t w z.
ApertiumResult apertium_interchunk(const char* input,
                                   const char* t2x_file,
                                   const char* datafile,
                                   const char* flags,
                                   const char* tmp_dir);

// apertium-postchunk. Flags: t w z.
ApertiumResult apertium_postchunk(const char* input,
                                  const char* t3x_file,
                                  const char* datafile,
                                  const char* flags,
                                  const char* tmp_dir);

// apertium-tagger (apply / -g mode). Additional flags passed through:
// f m p z d e.
ApertiumResult apertium_tagger_apply(const char* input,
                                     const char* prob_file,
                                     const char* flags,
                                     const char* tmp_dir);

// --- apertium-lex-tools ----------------------------------------------------

// lrx-proc. Flags: t d z m.
ApertiumResult apertium_lrx_proc(const char* input,
                                 const char* bin_path,
                                 const char* flags,
                                 const char* tmp_dir);

// --- apertium-separable ----------------------------------------------------

// lsx-proc. Flags: p r w z.
ApertiumResult apertium_lsx_proc(const char* input,
                                 const char* bin_path,
                                 const char* flags,
                                 const char* tmp_dir);

// --- apertium-recursive ----------------------------------------------------

// rtx-proc. Flags: a b e f F r s t T z.
ApertiumResult apertium_rtx_proc(const char* input,
                                 const char* rtx_file,
                                 const char* flags,
                                 const char* tmp_dir);

// --- apertium-anaphora -----------------------------------------------------

// apertium-anaphora. Flags: z d.
ApertiumResult apertium_anaphora(const char* input,
                                 const char* arx_file,
                                 const char* flags,
                                 const char* tmp_dir);

// --- cg3 (VISL CG-3) -------------------------------------------------------

// --- hfst (HFST) -----------------------------------------------------------

// hfst-apertium-proc. `flags` accepts:
//   a (analysis, default) / g / n / d / t (generation/tokenization)
//   z (null-flush)
//   c (case-sensitive) / w (dictionary-case)
ApertiumResult apertium_hfst_proc(const char* input,
                                  const char* bin_path,
                                  const char* flags,
                                  const char* tmp_dir);

// cg-proc. Flags recognized: t (trace), 1 (single run). Stream-format,
// wordform-case, word-forms, generation, and null-flush flags from the
// CLI aren't exposed by cg3's public C API; Apertium pipelines use the
// defaults (Apertium stream format), so we drop unknown flags silently.
ApertiumResult apertium_cg_proc(const char* input,
                                const char* grammar_file,
                                const char* flags,
                                const char* tmp_dir);

// --- top-level pipeline ----------------------------------------------------

// Parse the first non-blank line of `mode_file_path` as an Apertium mode
// line (stages separated by `|`), resolve file paths against
// `pair_base_dir`, and run the pipeline over `input`. Mirrors the
// Android NativePipeline.parseModeLine + runPipeline contract.
//
// `display_marks`: 1 keeps the leading '*' on unknown words; 0 strips
// all unknown-word markers (@/#/*) before returning.
ApertiumResult apertium_translate(const char* mode_file_path,
                                  const char* pair_base_dir,
                                  const char* input,
                                  int display_marks,
                                  const char* tmp_dir);

#ifdef __cplusplus
}
#endif

#endif  // APERTIUM_CORE_H
