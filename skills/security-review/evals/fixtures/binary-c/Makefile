CC ?= cc
CFLAGS ?= -fsanitize=address -g -O0 -fno-omit-frame-pointer -Wall

all: vuln fixed

vuln: vuln.c
	$(CC) $(CFLAGS) -o $@ $<

fixed: fixed.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f vuln fixed

.PHONY: all clean
