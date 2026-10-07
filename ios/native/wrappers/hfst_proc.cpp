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
#include <memory>

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
// HFST's header if present so ProcTransducer reads from the start of the
// transducer payload. Like hfst-proc, refuses a header that doesn't add up
// and a transducer that isn't in optimized-lookup format (HFST_OL,
// HFST_OLW), which ProcTransducer would read as garbage.
void skip_hfst3_header(std::istream& is) {
  const char* sig = "HFST";
  int loc = 0;
  const int sig_len = static_cast<int>(std::strlen(sig));
  for (loc = 0; loc < sig_len + 1; ++loc) {
    int c = is.get();
    if (c != sig[loc]) break;
  }
  if (loc == sig_len + 1) {
    unsigned short header_len = 0;
    is.read(reinterpret_cast<char*>(&header_len), sizeof(header_len));
    if (is.get() != '\0') throw std::runtime_error("malformed HFST header");
    // The null-terminated name/value pairs.
    int remaining = header_len;
    while (remaining > 0) {
      std::string name, value;
      if (!std::getline(is, name, '\0') || !std::getline(is, value, '\0')) break;
      remaining -= static_cast<int>(name.size() + value.size() + 2);
      if (name == "type" && value != "HFST_OL" && value != "HFST_OLW") {
        throw std::runtime_error("HFST transducer type " + value
                                 + " is not optimized-lookup (HFST_OL, HFST_OLW)");
      }
    }
    if (remaining != 0) throw std::runtime_error("malformed HFST header");
    return;
  }
  // Not an HFST3 header — rewind to the start.
  is.clear();
  is.seekg(0, std::ios::beg);
}

std::string hfst_proc(const char* input,
                      const char* bin_path,
                      const char* flags,
                      int max_analyses,
                      int max_weight_classes,
                      const char* tmp_dir) {
  if (!bin_path) throw std::runtime_error("bin_path is NULL");
  if (!tmp_dir)  throw std::runtime_error("tmp_dir is NULL");
  aix::ensure_exists(bin_path);

  // Option handling as in hfst-proc.cc's main(). The flags set globals that
  // outlive the call, so put every one back to its default first.
  displayWeightsFlag = false;
  maxAnalyses = max_analyses > 0 ? max_analyses : INT32_MAX;                  // -N
  maxWeightClasses = max_weight_classes > 0 ? max_weight_classes : INT32_MAX; // -l, --weight-classes
  processCompounds = false;
  rawMode = false;
  displayRawAnalysisInCG = false;
  char cmd = 0;
  char output_type = 0;
  char capitalization = 0;
  bool filter_compound_analyses = true;
  bool null_flush = false;
  for (const char* c = flags ? flags : ""; *c; ++c) {
    switch (*c) {
      case 'a': case 'g': case 'n': case 'd': case 't':
        if (cmd) throw std::runtime_error("multiple hfst-proc operation modes given");
        cmd = *c;
        break;
      case 'p':  // Apertium stream format, the default and the only one wired up
        if (output_type) throw std::runtime_error("multiple hfst-proc output modes given");
        output_type = *c;
        break;
      case 'k': filter_compound_analyses = false; break;
      case 'e': processCompounds = true; break;
      case 'W': displayWeightsFlag = true; break;
      case 'r': displayRawAnalysisInCG = true; break;
      case 'q': case 's': displayWeightsFlag = true; break;  // as hfst-proc.cc does
      case 'c': case 'w': case 'X': capitalization = *c; break;
      case 'z': null_flush = true; break;
      default:  // -v, and the -C/-x/-j output formats
        throw std::runtime_error(std::string("hfst-proc flag not supported on iOS: ") + *c);
    }
  }
  CapitalizationMode caps = IgnoreCase;
  switch (capitalization) {
    case 'c': caps = CaseSensitive; break;
    case 'w': caps = DictionaryCase; break;
    case 'X': caps = CaseSensitiveDictionaryCase; rawMode = true; break;
  }

  aix::TmpFile in_tmp = aix::spit_tmp(tmp_dir, "hfst_in", input);
  aix::TmpFile out_tmp(tmp_dir, "hfst_out");

  std::ifstream transducer_in(bin_path, std::ios::binary);
  if (!transducer_in) throw std::runtime_error("cannot open transducer");
  skip_hfst3_header(transducer_in);
  ProcTransducer transducer(transducer_in);
  transducer_in.close();

  {
    std::ifstream in_stream(in_tmp.path(), std::ios::binary);
    std::ofstream out_stream(out_tmp.path(), std::ios::binary);
    if (!in_stream || !out_stream)
      throw std::runtime_error("cannot open tmp I/O files");

    TokenIOStream ts(in_stream, out_stream, transducer.get_alphabet(),
                     null_flush, rawMode);

    // fmt before app: the applicator refers to the formatter, so it has to
    // go first.
    std::unique_ptr<OutputFormatter> fmt;
    std::unique_ptr<Applicator> app;
    switch (cmd) {
      case 't': app.reset(new TokenizationApplicator(transducer, ts)); break;
      case 'g': app.reset(new GenerationApplicator(transducer, ts, gm_unknown, caps)); break;
      case 'n': app.reset(new GenerationApplicator(transducer, ts, gm_clean, caps)); break;
      case 'd': app.reset(new GenerationApplicator(transducer, ts, gm_all, caps)); break;
      case 'a':
      default:
        fmt.reset(new ApertiumOutputFormatter(ts, filter_compound_analyses));
        app.reset(new AnalysisApplicator(transducer, ts, *fmt, caps));
        break;
    }
    app->apply();
  }
  return aix::slurp(out_tmp.path());
}

}  // namespace

extern "C" ApertiumResult apertium_hfst_proc(const char* input,
                                             const char* bin_path,
                                             const char* flags,
                                             int max_analyses,
                                             int max_weight_classes,
                                             const char* tmp_dir) {
  return aix::run_wrapper([&] {
    try {
      return hfst_proc(input, bin_path, flags, max_analyses,
                       max_weight_classes, tmp_dir);
    } catch (const HfstException& e) {
      // A corrupt .hfst makes ProcTransducer throw
      // TransducerHasWrongTypeException. HFST's exceptions don't derive from
      // std::exception, so name it here, with where HFST threw it.
      std::string file = e.file.substr(e.file.find_last_of('/') + 1);
      throw std::runtime_error("HFST " + e.name + " (" + file + ":"
                               + std::to_string(e.line) + ")");
    }
  });
}
