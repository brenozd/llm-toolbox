/* Negative control: same program, overflow seeded in vuln.c is fixed here.
 * build with `make`, then: ./fixed "$(cat input/overflow.txt)" -> "name too long", exit 1.
 */
#include <stdio.h>
#include <string.h>

static int copy_name(char *dst, size_t cap, const char *src) {
    if (strlen(src) >= cap) { /* FIXED: reject anything that would not fit */
        return -1;
    }
    strcpy(dst, src);
    return (int)strlen(dst);
}

int main(int argc, char **argv) {
    char buf[64];
    int n;

    if (argc < 2) {
        fprintf(stderr, "usage: %s NAME\n", argv[0]);
        return 2;
    }
    n = copy_name(buf, sizeof buf, argv[1]);
    if (n < 0) {
        fprintf(stderr, "name too long\n");
        return 1;
    }
    printf("hello %s (%d)\n", buf, n);
    return 0;
}
