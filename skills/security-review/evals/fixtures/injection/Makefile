CC ?= cc
CFLAGS ?= -g -O0

all: inject.bin

inject.bin: inject.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f inject.bin

.PHONY: all clean
