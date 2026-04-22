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

// Pick exactly one mode letter for lt-proc. The CLI accepts a/g/b/p/s/t/e.
char lt_proc_mode_letter(const std::string& flags) {
  for (char c : flags) {
    switch (c) {
      case 'a': case 'g': case 'b': case 'p':
      case 's': case 't': case 'e': return c;
      default: break;
    }
  }
  return 'a';  // default to analysis
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
    char mode = lt_proc_mode_letter(a.flags);
    char mode_s[2] = {mode, '\0'};
    std::string bin = take_file(a);
    return apertium_lt_proc(in.c_str(), bin.c_str(), mode_s, tmp_dir);
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
    return apertium_transfer(in.c_str(), trules.c_str(), datafile.c_str(),
                             biltrans.empty() ? nullptr : biltrans.c_str(),
                             a.flags.c_str(), tmp_dir);
  }
  if (tool == "apertium-interchunk") {
    std::string t2x  = take_file(a);
    std::string data = take_file(a);
    return apertium_interchunk(in.c_str(), t2x.c_str(), data.c_str(),
                               a.flags.c_str(), tmp_dir);
  }
  if (tool == "apertium-postchunk") {
    std::string t3x  = take_file(a);
    std::string data = take_file(a);
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
    return apertium_cg_proc(in.c_str(), grammar.c_str(), a.flags.c_str(), tmp_dir);
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

    std::string current(input ? input : "");
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

    std::string final_text = apply_marker_pref(current, display_marks != 0);
    result.output = aix::dup_cstr(final_text);
    if (!result.output) throw std::runtime_error("dup_cstr failed");
    return result;
  } catch (const std::exception& e) {
    result.error = aix::dup_cstr(e.what());
    return result;
  }
}
