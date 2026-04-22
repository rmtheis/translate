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
