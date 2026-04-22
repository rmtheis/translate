/* Stub glob for Android. Bionic doesn't export glob(3) and HFST's XfstCompiler
 * only calls it from the interactive xfst "print dir" command, which Android
 * never reaches (we never spawn xfst interactively). The stub returns a non-zero
 * error code so the caller prints a harmless "glob(...) = 1" line. */
#ifndef _APERTIUM_NDK_GLOB_SHIM_H_
#define _APERTIUM_NDK_GLOB_SHIM_H_

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    size_t gl_pathc;
    char **gl_pathv;
    size_t gl_offs;
} glob_t;

#define GLOB_NOSPACE  1
#define GLOB_ABORTED  2
#define GLOB_NOMATCH  3

static inline int glob(const char *pattern, int flags, int (*errfunc)(const char *, int), glob_t *pglob) {
    (void)pattern; (void)flags; (void)errfunc;
    if (pglob) {
        pglob->gl_pathc = 0;
        pglob->gl_pathv = 0;
        pglob->gl_offs = 0;
    }
    return GLOB_NOMATCH;
}

static inline void globfree(glob_t *pglob) { (void)pglob; }

#ifdef __cplusplus
}
#endif
#endif
