/* Eval fixture: exactly one seeded flaw, a stack buffer overflow in copy_name().
 * Build with `make` (ASan + -g) and run: ./vuln "$(cat input/overflow.txt)".
 */
#include <stdio.h>
#include <string.h>

static int copy_name(char *dst, const char *src) {
    strcpy(dst, src); /* SEEDED FLAW: no bound check, dst is 64 bytes */
    return (int)strlen(dst);
}

int main(int argc, char **argv) {
    char buf[64];
    int n;

    if (argc < 2) {
        fprintf(stderr, "usage: %s NAME\n", argv[0]);
        return 2;
    }
    n = copy_name(buf, argv[1]);
    printf("hello %s (%d)\n", buf, n);
    return 0;
}
