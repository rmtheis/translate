// apertium-ios-native/wrappers/hfst_proc.cpp
//
// Library-ified replacement for HFST's hfst-apertium-proc binary.
// hfst-proc.cc's main() glues together ProcTransducer + TokenIOStream +
// AnalysisApplicator. We do the same, over file-backed iostreams.
//
// The globals declared `extern` in hfst-proc.h (verboseFlag,
// silentFlag, processCompounds, …) are defined in hfst-proc.cc — which
// we excluded from libhfst_proc.a because it carries the binary's
// main(). Redefine them here at their default-off values.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <hfst-proc/hfst-proc.h>
#include <hfst-proc/applicators.h>
#include <hfst-proc/formatter.h>
#include <hfst-proc/tokenizer.h>
#include <hfst-proc/transducer.h>

#include <HfstExceptionDefs.h>

#include <cstring>
#include <fstream>
#include <iostream>

// --- redefinitions of globals and helpers from hfst-proc.cc -----------------
// hfst-proc.cc defines these; we deliberately did NOT archive its .o into
// libhfst_proc.a because it contains main(), so we re-provide them here.
bool verboseFlag = false;
bool silentFlag = true;
bool displayWeightsFlag = false;
bool displayUniqueFlag = false;
int  maxAnalyses = INT32_MAX;
int  maxWeightClasses = INT32_MAX;
bool preserveDiacriticRepresentationsFlag = false;
bool printDebuggingInformationFlag = false;
bool processCompounds = false;
bool rawMode = false;
bool displayRawAnalysisInCG = false;

// Tokenizer/applicator modules throw through stream_error() on malformed
// input. Mirror the upstream definition (hfst-proc.cc).
void stream_error(const char* e) {
  throw std::ios_base::failure(
    (std::string("Error: malformed input stream: ") + (e ? e : "") + "\n"));
}
void stream_error(std::string e) { stream_error(e.c_str()); }

namespace {

// Port of the static `handle_hfst3_header` from hfst-proc.cc. Skips
// HFST's magic-byte header if present so ProcTransducer reads from the
// start of the transducer payload.
void skip_hfst3_header(std::istream& is) {
  const char* sig = "HFST";
  int loc = 0;
  const int sig_len = static_cast<int>(std::strlen(sig));
  for (loc = 0; loc < sig_len + 1; ++loc) {
    int c = is.get();
    if (c != sig[loc]) break;
  }
  if (loc == sig_len + 1) {
    unsigned short remaining = 0;
    is.read(reinterpret_cast<char*>(&remaining), sizeof(remaining));
    if (is.get() != '\0') HFST_THROW(HfstException);
    // Skip the null-terminated name/value pairs.
    while (remaining > 0) {
      std::string tok;
      std::getline(is, tok, '\0');
      if (is.fail()) break;
      remaining -= static_cast<unsigned short>(tok.size() + 1);
    }
    return;
  }
  // Not an HFST3 header — rewind to the start.
  is.clear();
  is.seekg(0, std::ios::beg);
}

}  // namespace

extern "C" ApertiumResult apertium_hfst_proc(const char* input,
                                             const char* bin_path,
                                             const char* flags,
                                             const char* tmp_dir) {
  ApertiumResult result{nullptr, nullptr};
  std::string in_path, out_path;
  try {
    if (!bin_path) throw std::runtime_error("bin_path is NULL");
    if (!tmp_dir)  throw std::runtime_error("tmp_dir is NULL");
    aix::ensure_exists(bin_path);

    // Mode selector. hfst-apertium-proc uses:
    //   a — analysis (default, Apertium output format)
    //   g — generation (unknown mode)
    //   n — generation (clean)
    //   d — generation (debugged)
    //   t — tokenization
    char cmd = 'a';
    bool null_flush = false;
    CapitalizationMode caps = IgnoreCase;
    for (const char* c = flags ? flags : ""; *c; ++c) {
      switch (*c) {
        case 'a': case 'g': case 'n': case 'd': case 't': cmd = *c; break;
        case 'z': null_flush = true; break;
        case 'c': caps = CaseSensitive; break;
        case 'w': caps = DictionaryCase; break;
        // -p = Apertium output format. That IS the default in our
        // wrapper, so accept and ignore. Other output formats (-C CG,
        // -x Xerox, -j transliterate) are supported by the upstream
        // binary but not wired up here — Apertium pipelines always use -p.
        case 'p': break;
        default:
          throw std::runtime_error(std::string("unknown hfst-proc flag: ") + *c);
      }
    }

    in_path  = aix::spit_tmp(tmp_dir, "hfst_in", input);
    out_path = aix::make_tmp_file(tmp_dir, "hfst_out");

    std::ifstream transducer_in(bin_path, std::ios::binary);
    if (!transducer_in) throw std::runtime_error("cannot open transducer");
    skip_hfst3_header(transducer_in);
    ProcTransducer transducer(transducer_in);
    transducer_in.close();

    std::ifstream in_stream(in_path, std::ios::binary);
    std::ofstream out_stream(out_path, std::ios::binary);
    if (!in_stream || !out_stream)
      throw std::runtime_error("cannot open tmp I/O files");

    TokenIOStream ts(in_stream, out_stream, transducer.get_alphabet(),
                     null_flush, /*raw=*/false);

    Applicator* app = nullptr;
    OutputFormatter* fmt = nullptr;
    switch (cmd) {
      case 't': app = new TokenizationApplicator(transducer, ts); break;
      case 'g': app = new GenerationApplicator(transducer, ts, gm_unknown, caps); break;
      case 'n': app = new GenerationApplicator(transducer, ts, gm_clean, caps); break;
      case 'd': app = new GenerationApplicator(transducer, ts, gm_all, caps); break;
      case 'a':
      default:
        fmt = new ApertiumOutputFormatter(ts, /*filter_compound=*/false);
        app = new AnalysisApplicator(transducer, ts, *fmt, caps);
        break;
    }
    try {
      app->apply();
    } catch (...) {
      delete app; delete fmt;
      throw;
    }
    delete app; delete fmt;
    out_stream.close();

    std::string out = aix::slurp(out_path);
    aix::rm_quiet(in_path);
    aix::rm_quiet(out_path);
    result.output = aix::dup_cstr(out);
    if (!result.output) throw std::runtime_error("dup_cstr failed");
    return result;
  } catch (const std::exception& e) {
    aix::rm_quiet(in_path);
    aix::rm_quiet(out_path);
    result.error = aix::dup_cstr(e.what());
    return result;
  }
}
