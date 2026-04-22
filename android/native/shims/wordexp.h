/* Stub wordexp for Android API < 28.
 * cg3 only reaches this code path when a grammar path contains ~/$/*, which our
 * compiled pair packages never do. The stub returns an error to satisfy the link
 * and let the runtime fail loudly if the shell-expansion branch is ever taken. */
#ifndef _APERTIUM_NDK_WORDEXP_SHIM_H_
#define _APERTIUM_NDK_WORDEXP_SHIM_H_

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    size_t we_wordc;
    char **we_wordv;
    size_t we_offs;
} wordexp_t;

#define WRDE_NOCMD  0x04
#define WRDE_UNDEF  0x10

static inline int wordexp(const char *s, wordexp_t *p, int flags) {
    (void)s; (void)flags;
    if (p) {
        p->we_wordc = 0;
        p->we_wordv = 0;
        p->we_offs = 0;
    }
    return 1; /* WRDE_BADCHAR — tell the caller expansion failed */
}

static inline void wordfree(wordexp_t *p) { (void)p; }

#ifdef __cplusplus
}
#endif
#endif
