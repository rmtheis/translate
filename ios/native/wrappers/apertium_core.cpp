// apertium-ios-native/wrappers/apertium_core.cpp
//
// Top-level pipeline composer. Parses an Apertium .mode file and
// dispatches each stage to the matching library-ified wrapper,
// threading the string output of one stage into the next.
//
// Semantic mirror of apertium-android's NativePipeline.java —
// parseModeLine/runPipeline/applyMarkerPref/rewritePath all live here.

#include "apertium_core.h"
#include "wrapper_common.h"

#include <algorithm>
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <regex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

// Defined in hfst_proc.cpp; redeclared here so the mode-line parser can
// honor --weight-classes N by writing the hfst-proc global directly.
extern int maxWeightClasses;

namespace {

// Shell-style tokenizer. Handles "double", 'single', and bare words.
std::vector<std::string> tokenize(const std::string& line) {
  std::vector<std::string> out;
  std::string cur;
  enum { NONE, SQ, DQ } mode = NONE;
  auto flush = [&]{ if (!cur.empty() || mode != NONE) { out.push_back(cur); cur.clear(); } };
  for (size_t i = 0; i < line.size(); ++i) {
    char c = line[i];
    if (mode == SQ) {
      if (c == '\'') { out.push_back(cur); cur.clear(); mode = NONE; }
      else cur.push_back(c);
    } else if (mode == DQ) {
      if (c == '"') { out.push_back(cur); cur.clear(); mode = NONE; }
      else cur.push_back(c);
    } else {
      if (c == '\'') mode = SQ;
      else if (c == '"') mode = DQ;
      else if (std::isspace(static_cast<unsigned char>(c))) flush();
      else cur.push_back(c);
    }
  }
  if (!cur.empty()) out.push_back(cur);
  return out;
}

std::string basename_of(const std::string& p) {
  auto slash = p.find_last_of('/');
  return slash == std::string::npos ? p : p.substr(slash + 1);
}

// Mirrors NativePipeline.rewritePath. Debian-style
// /usr/share/apertium/apertium-<pkg>/<file> is rewritten to
// <pair_base>/<file>; relative data paths are joined to <pair_base>;
// absolute paths (other than the Debian prefix) pass through.
std::string rewrite_path(const std::string& tok, const std::string& pair_base) {
  if (tok.empty() || tok[0] == '-') return tok;
  static const std::string debian = "/usr/share/apertium/";
  if (tok.rfind(debian, 0) == 0) {
    return pair_base + "/" + basename_of(tok);
  }
  if (tok[0] == '/') return tok;
  auto has_suffix = [&](const char* s){
    size_t n = std::strlen(s);
    return tok.size() >= n && tok.compare(tok.size() - n, n, s) == 0;
  };
  if (tok.find('/') != std::string::npos
      || has_suffix(".bin") || has_suffix(".mode")
      || has_suffix(".t1x") || has_suffix(".t2x") || has_suffix(".t3x")
      || has_suffix(".rlx") || has_suffix(".rtx") || has_suffix(".prob")
      || has_suffix(".arx")) {
    return pair_base + "/" + tok;
  }
  return tok;
}

// Parse one mode-line segment's tokens; do $1/$2 substitution and path
// rewriting. $1 is Apertium's apertium(1) CLI substitution for the
// lt-proc-mode flag (default -g, for "generator"). $2 is typically empty.
std::vector<std::string> rewrite_stage(const std::vector<std::string>& toks,
                                       const std::string& pair_base) {
  std::vector<std::string> out;
  out.reserve(toks.size());
  if (toks.empty()) return out;
  out.push_back(toks[0]);  // tool name, not path-rewritten
  for (size_t i = 1; i < toks.size(); ++i) {
    const std::string& t = toks[i];
    if (t == "$1")      out.push_back("-g");
    else if (t == "$2") continue;
    else                out.push_back(rewrite_path(t, pair_base));
  }
  return out;
}

std::vector<std::vector<std::string>> parse_mode_line(const std::string& line,
                                                      const std::string& pair_base) {
  std::vector<std::vector<std::string>> stages;
  std::string seg;
  std::istringstream ss(line);
  while (std::getline(ss, seg, '|')) {
    // Trim
    size_t a = seg.find_first_not_of(" \t\r\n");
    if (a == std::string::npos) continue;
    size_t b = seg.find_last_not_of(" \t\r\n");
    std::string trimmed = seg.substr(a, b - a + 1);
    auto toks = tokenize(trimmed);
    if (toks.empty()) continue;
    stages.push_back(rewrite_stage(toks, pair_base));
  }
  return stages;
}

// Split a stage's argv into {flags-letters, positional-files, opts}.
// Flags that look like `-X` or `--long` are collected as single-letter
// strings (we concatenate all single-letter short flags into one
// string per wrapper's convention). Long options get a tiny whitelist;
// long options that take an argument (like `--weight-classes N`) are
// stashed in a key→value map so downstream can honor them.
struct Argv {
  std::string flags;
  std::vector<std::string> files;
  std::unordered_map<std::string, std::string> long_opts_with_arg;
};

// Long options that take a positional argument.
const std::vector<std::string>& long_opts_with_arg_names() {
  static const std::vector<std::string> n{
    "--weight-classes", "--max-analyses", "--sections",
  };
  return n;
}

Argv classify_argv(const std::vector<std::string>& argv) {
  Argv a;
  for (size_t i = 1; i < argv.size(); ++i) {
    const std::string& t = argv[i];
    if (t.size() >= 2 && t[0] == '-' && t[1] != '-') {
      for (size_t j = 1; j < t.size(); ++j) a.flags.push_back(t[j]);
    } else if (t.size() > 2 && t.substr(0, 2) == "--") {
      // Long option — may take an argument from argv[i+1].
      const auto& arg_opts = long_opts_with_arg_names();
      if (std::find(arg_opts.begin(), arg_opts.end(), t) != arg_opts.end()
          && i + 1 < argv.size()) {
        a.long_opts_with_arg[t] = argv[i + 1];
        ++i;  // consume value
        continue;
      }
      if      (t == "--null-flush") a.flags.push_back('z');
      else if (t == "--trace")      a.flags.push_back('t');
      else if (t == "--first")      a.flags.push_back('1');
      else if (t == "--unmerge")    a.flags.push_back('u');  // lt-merge
      // else silently drop; wrappers reject unknown short flags.
    } else {
      a.files.push_back(t);
    }
  }
  return a;
}

std::string take_file(Argv& a) {
  if (a.files.empty())
    throw std::runtime_error("expected file argument");
  std::string s = a.files.front();
  a.files.erase(a.files.begin());
  return s;
}

std::string opt_file(Argv& a) {
  if (a.files.empty()) return "";
  std::string s = a.files.front();
  a.files.erase(a.files.begin());
  return s;
}

// Pick the mode for lt-proc. The CLI accepts a/g/b/p/s/t/e. As in lt_proc.cc,
// -b wins over -g, and -b together with -g is bilingual generation (gm_bilgen),
// which apertium_lt_proc reads as "bg": `lt-proc $1 -b X.autogen.bin` (nob-nno,
// spa-cat, ...) and `lt-proc -b $1 ...` (sme-nob) arrive as flags "gb" / "bg".
// Otherwise the first mode letter.
std::string lt_proc_mode(const std::string& flags) {
  if (flags.find('b') != std::string::npos)
    return flags.find('g') != std::string::npos ? "bg" : "b";
  for (char c : flags) {
    switch (c) {
      case 'a': case 'g': case 'p':
      case 's': case 't': case 'e': return std::string(1, c);
      default: break;
    }
  }
  return "a";  // default to analysis
}

// Strip flags that aren't single-letter mode selectors.
std::string non_mode_flags(const std::string& flags) {
  std::string out;
  for (char c : flags) {
    switch (c) {
      case 'a': case 'g': case 'b': case 'p':
      case 's': case 't': case 'e':
        break;  // mode selector; don't forward as a "flag"
      default:
        out.push_back(c);
        break;
    }
  }
  return out;
}

// apertium-transfer/-interchunk/-postchunk take the rules XML and the .bin
// compiled from it; the .bin's pattern matcher returns rule numbers that index
// the XML's <rule>s, so the two must match. Apertium builds X.t1x.bin from
// X.t1x, and a pair with rule variants (alt="oci@aran") ships the
// variant-filtered X.t1x next to the unfiltered apertium-<pkg>.X.t1x. The
// Debian build of apertium-oci-cat (2022, 357b2f07) passes the unfiltered file
// with oci-cat.t1x.bin (155 vs 132 rules; t2x/t3x mismatch too), so transfer
// ran the wrong rule's actions and segfaulted on "L'ostal es grand.". Upstream
// fixed modes.xml in a81f6fd1 (2025-03). When X.tNx exists, read it instead.
std::string rules_xml_for_bin(const std::string& xml, const std::string& bin) {
  static const std::string ext = ".bin";
  if (bin.size() <= ext.size()
      || bin.compare(bin.size() - ext.size(), ext.size(), ext) != 0) {
    return xml;
  }
  std::string src = bin.substr(0, bin.size() - ext.size());
  if (src == xml || ::access(src.c_str(), R_OK) != 0) return xml;
  return src;
}

// cg-proc prints a CG-3 dependency link as a tag, <#N→M>, on every cohort a
// SETPARENT/SETCHILD rule touched. CG-3 added that to the Apertium stream
// format in f5d37748 (2022-01); grammars written before then don't expect it.
// hbs-mkd.rlx's experimental SETPARENT rules fire on adjective + noun ("Dobar
// dan."), apertium-pretransfer then reads the tag's '#' as a multiword split
// (^Dobar#1→2><adj>…<$), and apertium-transfer segfaults on the result. Android
// runs the real binaries and crashes the same way. No stage in the pairs we
// ship reads the tags, so drop them. Only <#digits→digits> inside a lexical
// unit is dropped; escaped characters and [superblanks] pass through.
bool is_dependency_tag(const std::string& s, size_t begin, size_t end) {
  static const std::string arrow = "\xE2\x86\x92";  // U+2192 in UTF-8
  size_t i = begin;
  if (i >= end || s[i] != '#') return false;
  ++i;
  auto digits = [&]() {
    size_t start = i;
    while (i < end && std::isdigit(static_cast<unsigned char>(s[i]))) ++i;
    return i > start;
  };
  if (!digits()) return false;
  if (s.compare(i, arrow.size(), arrow) != 0) return false;
  i += arrow.size();
  return digits() && i == end;
}

std::string strip_dependency_tags(const std::string& s) {
  if (s.find("\xE2\x86\x92") == std::string::npos) return s;
  std::string out;
  out.reserve(s.size());
  bool in_lu = false;
  for (size_t i = 0; i < s.size(); ++i) {
    char c = s[i];
    if (c == '\\' && i + 1 < s.size()) {
      out.push_back(c);
      out.push_back(s[++i]);
      continue;
    }
    if (!in_lu && c == '[') {
      // Superblank or [[wordbound blank]]: copy through the closing ']'.
      size_t j = i;
      while (j < s.size() && s[j] != ']') j += (s[j] == '\\') ? 2 : 1;
      if (j >= s.size()) j = s.size() - 1;
      out.append(s, i, j - i + 1);
      i = j;
      continue;
    }
    if (c == '^') {
      in_lu = true;
    } else if (c == '$') {
      in_lu = false;
    } else if (c == '<' && in_lu) {
      size_t close = s.find('>', i + 1);
      if (close != std::string::npos && is_dependency_tag(s, i + 1, close)) {
        i = close;
        continue;
      }
    }
    out.push_back(c);
  }
  return out;
}

// ---------- stage dispatch ----------

ApertiumResult run_stage(const std::vector<std::string>& stage,
                         const std::string& in,
                         const char* tmp_dir) {
  if (stage.empty()) {
    ApertiumResult r{aix::dup_cstr(in), nullptr};
    return r;
  }
  const std::string& tool = stage[0];
  Argv a = classify_argv(stage);

  if (tool == "lt-proc") {
    std::string mode = lt_proc_mode(a.flags);
    std::string bin = take_file(a);
    return apertium_lt_proc(in.c_str(), bin.c_str(), mode.c_str(), tmp_dir);
  }
  if (tool == "lt-merge") {
    return apertium_lt_merge(in.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "apertium-tagger") {
    // -g is always set by our wrapper; strip it from the flag passthrough.
    std::string fl = a.flags;
    fl.erase(std::remove(fl.begin(), fl.end(), 'g'), fl.end());
    std::string prob = take_file(a);
    return apertium_tagger_apply(in.c_str(), prob.c_str(), fl.c_str(), tmp_dir);
  }
  if (tool == "apertium-pretransfer") {
    return apertium_pretransfer(in.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "apertium-posttransfer") {
    return apertium_posttransfer(in.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "apertium-transfer") {
    std::string trules   = take_file(a);
    std::string datafile = take_file(a);
    std::string biltrans = opt_file(a);
    trules = rules_xml_for_bin(trules, datafile);
    return apertium_transfer(in.c_str(), trules.c_str(), datafile.c_str(),
                             biltrans.empty() ? nullptr : biltrans.c_str(),
                             a.flags.c_str(), tmp_dir);
  }
  if (tool == "apertium-interchunk") {
    std::string t2x  = take_file(a);
    std::string data = take_file(a);
    t2x = rules_xml_for_bin(t2x, data);
    return apertium_interchunk(in.c_str(), t2x.c_str(), data.c_str(),
                               a.flags.c_str(), tmp_dir);
  }
  if (tool == "apertium-postchunk") {
    std::string t3x  = take_file(a);
    std::string data = take_file(a);
    t3x = rules_xml_for_bin(t3x, data);
    return apertium_postchunk(in.c_str(), t3x.c_str(), data.c_str(),
                              a.flags.c_str(), tmp_dir);
  }
  if (tool == "lrx-proc") {
    // The CLI's -m flag is a backwards-compat no-op; the wrapper treats
    // it as such. Strip non-mode-like flags as-is.
    std::string bin = take_file(a);
    return apertium_lrx_proc(in.c_str(), bin.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "lsx-proc") {
    std::string bin = take_file(a);
    return apertium_lsx_proc(in.c_str(), bin.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "rtx-proc") {
    std::string rtx = take_file(a);
    return apertium_rtx_proc(in.c_str(), rtx.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "cg-proc") {
    std::string grammar = take_file(a);
    ApertiumResult r = apertium_cg_proc(in.c_str(), grammar.c_str(),
                                        a.flags.c_str(), tmp_dir);
    if (r.output) {
      std::string stripped = strip_dependency_tags(r.output);
      if (stripped.size() != std::strlen(r.output)) {
        std::free(r.output);
        r.output = aix::dup_cstr(stripped);
        if (!r.output) r.error = aix::dup_cstr("dup_cstr failed");
      }
    }
    return r;
  }
  if (tool == "apertium-anaphora") {
    std::string arx = take_file(a);
    return apertium_anaphora(in.c_str(), arx.c_str(), a.flags.c_str(), tmp_dir);
  }
  if (tool == "hfst-proc" || tool == "hfst-apertium-proc") {
    std::string bin = take_file(a);
    // --weight-classes N sets hfst-proc's global before the wrapper runs.
    auto it = a.long_opts_with_arg.find("--weight-classes");
    if (it != a.long_opts_with_arg.end()) {
      try { maxWeightClasses = std::stoi(it->second); } catch (...) {}
    } else {
      maxWeightClasses = INT32_MAX;
    }
    return apertium_hfst_proc(in.c_str(), bin.c_str(), a.flags.c_str(), tmp_dir);
  }
  ApertiumResult r{nullptr, aix::dup_cstr("unknown tool: " + tool)};
  return r;
}

// Read the first non-empty, non-comment line from the mode file.
std::string read_mode_line(const std::string& path) {
  std::ifstream f(path);
  if (!f) throw std::runtime_error("cannot open mode file: " + path);
  std::string line;
  while (std::getline(f, line)) {
    size_t a = line.find_first_not_of(" \t\r\n");
    if (a == std::string::npos) continue;
    if (line[a] == '#') continue;
    return line.substr(a);
  }
  throw std::runtime_error("empty mode file: " + path);
}

// Mirror NativePipeline.escapeStream: backslash-escape the characters that
// are syntax in Apertium's stream format (lttoolbox's escaped_chars, the set
// apertium-destxt escapes). Mode files start at lt-proc, not at the
// deformatter, so raw user text must be escaped before stage 1: unescaped,
// lt-proc throws "Malformed input stream" at the first / @ $ ... (a date,
// an email, a URL); < silently cuts the text off and [ leaves the rest
// untranslated.
// All of these are ASCII, so walking UTF-8 bytes is safe.
bool is_stream_reserved(char c) {
  switch (c) {
    case '\\': case '[': case ']': case '{': case '}':
    case '^': case '$': case '/': case '@': case '<': case '>':
      return true;
    default:
      return false;
  }
}

std::string escape_stream(const std::string& text) {
  std::string out;
  out.reserve(text.size() + 8);
  for (char c : text) {
    if (is_stream_reserved(c)) out.push_back('\\');
    out.push_back(c);
  }
  return out;
}

// Mirror NativePipeline.unescapeStream: drop the stream escapes that
// survive to the final output (\X -> X), as apertium-retxt does. Runs after
// apply_marker_pref, which recognizes escaped markers (\@word) itself.
std::string unescape_stream(const std::string& text) {
  std::string once;
  once.reserve(text.size());
  for (size_t i = 0; i < text.size(); ++i) {
    if (text[i] == '\\' && i + 1 < text.size()) ++i;
    once.push_back(text[i]);
  }
  // lttoolbox's fallback for a word it can't generate ("#joan@correu.cat",
  // "#$20") writes the still-escaped text through its escaper a second time,
  // so those words keep one level ("\@") after the pass above. Drop a
  // backslash left in front of a stream character; the only casualty is a
  // user-typed backslash directly before one of them.
  std::string out;
  out.reserve(once.size());
  for (size_t i = 0; i < once.size(); ++i) {
    if (once[i] == '\\' && i + 1 < once.size() && once[i + 1] != '\\'
        && is_stream_reserved(once[i + 1])) {
      continue;
    }
    out.push_back(once[i]);
  }
  return out;
}

// Mirror NativePipeline.applyMarkerPref:
// @word / #word / *word (optionally backslash-escaped) at start-of-string
// or after whitespace → normalize to a single * (display_marks=true) or
// strip outright (display_marks=false).
// Hand-rolled iteration because libc++'s std::regex doesn't implement
// ECMAScript lookbehind — using \\?[@#*](?=\S) wouldn't fly either.
std::string apply_marker_pref(const std::string& text, bool display_marks) {
  std::string out;
  out.reserve(text.size());
  auto is_space = [](char c) {
    return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f';
  };
  auto is_marker = [](char c) { return c == '@' || c == '#' || c == '*'; };
  const char* replacement = display_marks ? "*" : "";
  size_t i = 0;
  while (i < text.size()) {
    bool at_boundary = (i == 0) || is_space(text[i - 1]);
    char c = text[i];
    // Optional backslash escape before the marker.
    if (at_boundary && c == '\\' && i + 1 < text.size()
        && is_marker(text[i + 1]) && i + 2 < text.size()
        && !is_space(text[i + 2]) && text[i + 2] != '\0') {
      out.append(replacement);
      i += 2;  // skip \\ + marker; the following non-space char stays
      continue;
    }
    if (at_boundary && is_marker(c) && i + 1 < text.size()
        && !is_space(text[i + 1])) {
      out.append(replacement);
      i += 1;
      continue;
    }
    out.push_back(c);
    ++i;
  }
  return out;
}

}  // namespace

extern "C" ApertiumResult apertium_translate(const char* mode_file_path,
                                             const char* pair_base_dir,
                                             const char* input,
                                             int display_marks,
                                             const char* tmp_dir) {
  ApertiumResult result{nullptr, nullptr};
  try {
    if (!mode_file_path) throw std::runtime_error("mode_file_path is NULL");
    if (!pair_base_dir)  throw std::runtime_error("pair_base_dir is NULL");
    if (!tmp_dir)        throw std::runtime_error("tmp_dir is NULL");

    std::string line = read_mode_line(mode_file_path);
    auto stages = parse_mode_line(line, pair_base_dir);
    if (stages.empty()) {
      result.output = aix::dup_cstr(input ? input : "");
      return result;
    }

    std::string current = escape_stream(input ? input : "");
    const char* trace = std::getenv("APERTIUM_TRACE");
    const bool trace_on = trace && trace[0] && trace[0] != '0';
    for (size_t i = 0; i < stages.size(); ++i) {
      ApertiumResult r = run_stage(stages[i], current, tmp_dir);
      if (r.error) {
        std::string prefix = "stage " + std::to_string(i + 1) + " ("
                           + stages[i][0] + "): ";
        std::string combined = prefix + r.error;
        apertium_result_free(r);
        throw std::runtime_error(combined);
      }
      current = r.output ? r.output : "";
      apertium_result_free(r);
      if (trace_on) {
        std::fprintf(stderr, "[stage %zu %-20s] %s\n",
                     i + 1, stages[i][0].c_str(), current.c_str());
      }
    }

    std::string final_text =
        unescape_stream(apply_marker_pref(current, display_marks != 0));
    result.output = aix::dup_cstr(final_text);
    if (!result.output) throw std::runtime_error("dup_cstr failed");
    return result;
  } catch (const std::exception& e) {
    result.error = aix::dup_cstr(e.what());
    return result;
  }
}
