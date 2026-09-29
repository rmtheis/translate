//
//  ApertiumCore.swift
//  Translate
//
//  Swift wrapper over the C API in apertium_core.h. All translation
//  calls are serialized on a dedicated DispatchQueue — Apertium's
//  globals (getopt optind, ICU caches, per-tool statics) are not
//  thread-safe.
//

import Foundation

enum ApertiumError: Error {
    case failed(String)
    case missingPair(String)
}

final class ApertiumEngine {
    static let shared = ApertiumEngine()

    private let queue = DispatchQueue(label: "com.qvyshift.translate.apertium",
                                      qos: .userInitiated)

    /// Run the full `.mode` pipeline on `input`. Blocks the calling thread;
    /// use `translateAsync(…)` from the UI.
    func translate(input: String,
                   modeFile: URL,
                   pairBaseDir: URL,
                   displayMarks: Bool = true) throws -> String {
        try queue.sync {
            try Self.runUnguarded(input: input,
                                  modeFile: modeFile,
                                  pairBaseDir: pairBaseDir,
                                  displayMarks: displayMarks)
        }
    }

    func translateAsync(input: String,
                        modeFile: URL,
                        pairBaseDir: URL,
                        displayMarks: Bool = true,
                        completion: @escaping (Result<String, Error>) -> Void) {
        // Hop onto our serial queue without re-entering translate()
        // synchronously — translate() would call queue.sync and deadlock
        // against ourselves.
        queue.async {
            do {
                let out = try Self.runUnguarded(input: input,
                                                modeFile: modeFile,
                                                pairBaseDir: pairBaseDir,
                                                displayMarks: displayMarks)
                DispatchQueue.main.async { completion(.success(out)) }
            } catch {
                DispatchQueue.main.async { completion(.failure(error)) }
            }
        }
    }

    /// Unserialized call into the C API. Must only be invoked with the
    /// serial `queue` already owned — either via queue.sync (translate)
    /// or via queue.async body (translateAsync).
    private static func runUnguarded(input: String,
                                     modeFile: URL,
                                     pairBaseDir: URL,
                                     displayMarks: Bool) throws -> String {
        // apertium_translate escapes the stream metacharacters, but lrx-proc
        // (apertium-lex-tools) still mis-reads an escaped "^" in the text after
        // the last word as the start of a lexical unit and swallows the rest of
        // the stream. That tail is never translated anyway, so hold it back and
        // re-attach it verbatim — same as NativePipeline.caretTailStart on Android.
        let (head, tail) = splitCaretTail(input)
        if !tail.isEmpty && head.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return input
        }
        let translated = try runPipeline(input: head, modeFile: modeFile,
                                         pairBaseDir: pairBaseDir, displayMarks: displayMarks)
        guard !tail.isEmpty else { return translated }
        var out = translated
        // Drop the line break the pipeline echoes for the newline fed to stage 1.
        while let last = out.last, last.isNewline { out.removeLast() }
        return out + tail
    }

    /// Splits off the trailing text that must bypass the pipeline: from the
    /// first "^" after the last letter or digit, together with the whitespace
    /// before it. `tail` is empty when there is nothing to hold back.
    static func splitCaretTail(_ text: String) -> (head: String, tail: String) {
        let scalars = text.unicodeScalars
        var afterLastWord = scalars.startIndex
        var i = scalars.startIndex
        while i < scalars.endIndex {
            let next = scalars.index(after: i)
            if isLetterOrDigit(scalars[i]) { afterLastWord = next }
            i = next
        }
        guard var start = scalars[afterLastWord...].firstIndex(of: "^") else {
            return (text, "")
        }
        while start > afterLastWord {
            let prev = scalars.index(before: start)
            guard scalars[prev].properties.isWhitespace else { break }
            start = prev
        }
        return (String(String.UnicodeScalarView(scalars[..<start])),
                String(String.UnicodeScalarView(scalars[start...])))
    }

    /// Same classes as Java's Character.isLetterOrDigit (Unicode L* and Nd).
    private static func isLetterOrDigit(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.properties.generalCategory {
        case .uppercaseLetter, .lowercaseLetter, .titlecaseLetter,
             .modifierLetter, .otherLetter, .decimalNumber:
            return true
        default:
            return false
        }
    }

    private static func runPipeline(input: String,
                                    modeFile: URL,
                                    pairBaseDir: URL,
                                    displayMarks: Bool) throws -> String {
        let tmp = NSTemporaryDirectory()
        let result = input.withCString { inputC in
            modeFile.path.withCString { modeC in
                pairBaseDir.path.withCString { baseC in
                    tmp.withCString { tmpC in
                        apertium_translate(modeC, baseC, inputC,
                                           displayMarks ? 1 : 0, tmpC)
                    }
                }
            }
        }
        defer { apertium_result_free(result) }
        if let err = result.error {
            throw ApertiumError.failed(String(cString: err))
        }
        guard let out = result.output else {
            throw ApertiumError.failed("no output and no error")
        }
        return String(cString: out)
    }
}
